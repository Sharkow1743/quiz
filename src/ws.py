# websocket_manager.py
import inspect
from types import SimpleNamespace
from typing import Any, Dict, List, Set
from fastapi import WebSocket, HTTPException
from pydantic import BaseModel, ValidationError
import json

from fastsession.fast_session_middleware import FastSession
from fastsession_database_store import DatabaseStore
import models

class WebSocketDispatcher:
    def __init__(self, router, session_store: DatabaseStore, secret_key: str):
        self.routes = {}
        self.session_store = session_store
        self.secret_key = secret_key
        
        # New: Tracking for Real-Time Broadcasting
        self.user_connections: Dict[str, WebSocket] = {} # user_id -> ws
        self.quiz_rooms: Dict[str, Set[str]] = {} # quiz_id -> set of user_ids
        
        self._analyze_routes(router)

    def _analyze_routes(self, router):
        for route in router.routes:
            if "POST" in route.methods:
                sig = inspect.signature(route.endpoint)
                model_class = next((p.annotation for p in sig.parameters.values() 
                                   if inspect.isclass(p.annotation) and issubclass(p.annotation, BaseModel)), None)
                self.routes[route.path] = {"func": route.endpoint, "model": model_class}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        
        # Extract user_id from session on connect
        session_mgr = FastSession(self.session_store, "sid", self.secret_key, websocket.cookies.get("sid"), response=SimpleNamespace())
        session = session_mgr.get_session()
        
        if session and "user" in session:
            user = json.loads(session["user"])
            self.user_connections[user["id"]] = websocket

    def disconnect(self, websocket: WebSocket):
        # Remove connection
        for user_id, ws in list(self.user_connections.items()):
            if ws == websocket:
                del self.user_connections[user_id]
                # Remove from rooms
                for room in self.quiz_rooms.values():
                    room.discard(user_id)

    async def join_room(self, quiz_id: str, user_id: str):
        if quiz_id not in self.quiz_rooms:
            self.quiz_rooms[quiz_id] = set()
        self.quiz_rooms[quiz_id].add(user_id)

    async def broadcast(self, quiz_id: str, command: str, data: Any):
        """Allows endpoints to broadcast events to everyone in a quiz."""
        if quiz_id not in self.quiz_rooms: return
        
        response = models.WSResponse(type="command", command=command, data=data)
        for user_id in self.quiz_rooms[quiz_id]:
            ws = self.user_connections.get(user_id)
            if ws:
                await ws.send_json(response.model_dump())

    async def handle_message(self, websocket: WebSocket, raw_data: dict):
        try:
            ws_req = models.WSRequest(**raw_data)
        except ValidationError as e:
            await websocket.send_json(models.WSResponse(type="response", status=422, error=str(e)).model_dump())
            return

        route_info = self.routes.get(ws_req.path)
        if not route_info:
            await websocket.send_json(models.WSResponse(type="response", path=ws_req.path, status=404, error="Not found").model_dump())
            return

        session_mgr = FastSession(self.session_store, "sid", self.secret_key, websocket.cookies.get("sid"), response=SimpleNamespace())
        mock_request = SimpleNamespace(
            state=SimpleNamespace(session=session_mgr), 
            cookies=websocket.cookies,
            app=SimpleNamespace(state=SimpleNamespace(ws_dispatcher=self)) # Inject dispatcher!
        )

        try:
            kwargs = {"request": mock_request}
            if route_info["model"]:
                data_key = next(k for k, v in inspect.signature(route_info["func"]).parameters.items() if v.annotation == route_info["model"])
                kwargs[data_key] = route_info["model"](**ws_req.body)
            
            result = await route_info["func"](**kwargs)
            
            resp = models.WSResponse(type="response", path=ws_req.path, status=200, data=result)
            await websocket.send_json(resp.model_dump())

        except HTTPException as e:
            await websocket.send_json(models.WSResponse(type="response", path=ws_req.path, status=e.status_code, error=e.detail).model_dump())