import os
import string
from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from fastsession import FastSessionMiddleware
from fastsession.fast_session_middleware import FastSession

from fastsession_database_store import DatabaseStore

from database import DatabaseHandler
import models
from quiz import ACTIVE_QUIZZES, BlitzStateMachine

import hashlib

from ws import WebSocketDispatcher

SECRET_KEY=os.getenv('secret_key', '1234')
SESSION_STORE=DatabaseStore()

app = FastAPI()
api_router = APIRouter(prefix="/api")

app.add_middleware(FastSessionMiddleware,
                   secret_key=SECRET_KEY,
                   store=SESSION_STORE,
                   http_only=True, 
                   secure=False,
                   max_age=0,
                   session_cookie="sid",
                   session_object="session" 
                   )

users = DatabaseHandler(models.User)
quizes = DatabaseHandler(models.Quiz)

@api_router.post("/user/auth")
async def auth(request: Request, data: models.AuthRequest):
    session_mgr: FastSession = request.state.session
    session = session_mgr.get_session()

    password = data.password

    # validating
    if (len(password) < 4): raise HTTPException(status_code=400, detail='Password cannot be shorter that 4 characters')

    for char in password:
        if char not in string.ascii_letters + string.digits + string.punctuation:
            raise HTTPException(status_code=400, detail='Password contains illegal characters')
    
    # encryption
    try:
        bytes_password = password.encode('ascii')
    except UnicodeEncodeError:
        raise HTTPException(status_code=400, detail='Password contains illegal characters')
    
    password = hashlib.sha256(bytes_password).hexdigest()

    # password checking
    user = users.get_by(username=data.username)
    if not user:
        user = models.User(username=data.username, password_hash=password)

    if password != user.password_hash: raise HTTPException(status_code=401, detail='Wrong password')

    # saving
    session['user'] = user.model_dump_json()
    session_mgr.save_session()

    users.save(user)

    return user

@api_router.post('/quiz/create')
async def create_quiz(request: Request):  # renamed to create_quiz to avoid collision
    # Answers require UUIDs!
    correct_answer = models.Answer(text='test1')
    wrong_answer = models.Answer(text='test2')
    
    quiz = models.Quiz(
        questions=[
            models.Question(
                text='test', 
                variants=[correct_answer, wrong_answer], 
                correct_answer_id=correct_answer.id, 
                time_limit=360,
                points=100  # Question requires points!
            )
        ]
    )
    quizes.save(quiz)
    return {"status": "created", "id": quiz.id}


@api_router.post('/quiz/join')
async def join_quiz(request: Request, data: models.QuizSimpleRequest): # Use the Pydantic model
    session = request.state.session.get_session()
    user = models.User.model_validate_json(session["user"])
    
    dispatcher = request.app.state.ws_dispatcher
    
    # data.quiz_id is parsed perfectly as a UUID object by Pydantic
    quiz_uuid = data.quiz_id 
    # Use string for the dictionary key
    quiz_id_str = str(data.quiz_id) 

    quiz = quizes.get_by(id=quiz_uuid)
    
    if quiz_id_str not in ACTIVE_QUIZZES:
        # PASS THE UUID OBJECT TO THE DATABASE HERE:
        quiz_data = quizes.get_by(id=quiz_uuid)
        
        if not quiz_data:
            raise HTTPException(status_code=404, detail="Quiz not found")
            
        ACTIVE_QUIZZES[quiz_id_str] = BlitzStateMachine(quiz_id_str, quiz_data, dispatcher)
        
    await dispatcher.join_room(quiz_id_str, str(user.id))
    ACTIVE_QUIZZES[quiz_id_str].scores[str(user.id)] = 0
    await dispatcher.broadcast(quiz_id_str, "PLAYER_JOINED", {"user_id": str(user.id)})

    safe_quiz = models.QuizWithoutAnswer.model_validate(quiz)
    
    return {"status": "joined", "quiz": safe_quiz.model_dump_json()}


@api_router.post('/quiz/start')
async def start_quiz(request: Request, data: models.QuizSimpleRequest): # Use the Pydantic model
    quiz_id_str = str(data.quiz_id)
    
    if quiz_id_str in ACTIVE_QUIZZES:
        # Start the background game loop!
        await ACTIVE_QUIZZES[quiz_id_str].start()
        
    return {"status": "started"}

@api_router.post('/quiz/question/answer')
async def answer(request: Request, data: models.AnswerRequest):
    session = request.state.session.get_session()
    user = models.User.model_validate_json(session["user"])
    
    quiz_id = str(data.quiz_id)
    
    if quiz_id not in ACTIVE_QUIZZES:
        raise HTTPException(status_code=404, detail="Quiz not active")
        
    # Process the blitz answer
    machine = ACTIVE_QUIZZES[quiz_id]
    accepted = await machine.submit_answer(str(user.id), str(data.answer.id))
    
    if not accepted:
        raise HTTPException(status_code=400, detail="Too late or already answered")

    return {"status": "recorded"}

    

ws_dispatcher = WebSocketDispatcher(api_router, SESSION_STORE, SECRET_KEY)
app.state.ws_dispatcher = ws_dispatcher

@api_router.websocket('/ws')
async def ws(websocket: WebSocket):
    await ws_dispatcher.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await ws_dispatcher.handle_message(websocket, data)
    except Exception:
        websocket.send_json(models.WSResponse(type='error', status=500, error='Internal error').model_dump_json())
    finally:
        ws_dispatcher.disconnect(websocket)

app.include_router(api_router)
app.mount("/", StaticFiles(directory=os.getenv('public', "public"), html=True), name="public")