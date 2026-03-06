# blitz_state_machine.py
import asyncio
import time
from enum import Enum
from typing import Dict, Any

class QuizState(Enum):
    WAITING = "waiting"
    QUESTION = "question"
    EVALUATING = "evaluating"
    FINISHED = "finished"

class BlitzStateMachine:
    def __init__(self, quiz_id: str, quiz_data: Any, dispatcher):
        self.quiz_id = str(quiz_id)
        self.quiz_data = quiz_data
        self.dispatcher = dispatcher
        
        self.state = QuizState.WAITING
        self.scores: Dict[str, int] = {}
        self.current_q_idx = -1
        
        # Blitz Tracking
        self.q_start_time = 0.0
        self.current_answers = set()
        self.timer_task = None

    async def start(self):
        if self.state != QuizState.WAITING: return
        self.current_q_idx = 0
        await self._next_question()

    async def _next_question(self):
        if self.current_q_idx >= len(self.quiz_data.questions):
            self.state = QuizState.FINISHED
            await self.dispatcher.broadcast(self.quiz_id, "QUIZ_FINISHED", {"scores": self.scores})
            return

        self.state = QuizState.QUESTION
        self.current_answers.clear()
        self.q_start_time = time.time()
        
        q = self.quiz_data.questions[self.current_q_idx]
        
        # Strip the right answer before sending to frontend!
        safe_q = q.model_dump(exclude={"correct_answer_id"})
        
        await self.dispatcher.broadcast(self.quiz_id, "QUESTION_STARTED", {"question": safe_q})

        self.timer_task = asyncio.create_task(self._wait_for_timer(q.time_limit))

    async def _wait_for_timer(self, time_limit: int):
        await asyncio.sleep(time_limit)
        if self.state == QuizState.QUESTION:
            await self._evaluate()

    async def submit_answer(self, user_id: str, answer_id: str):
        if self.state != QuizState.QUESTION or user_id in self.current_answers:
            return False

        self.current_answers.add(user_id)
        
        q = self.quiz_data.questions[self.current_q_idx]
        time_taken = time.time() - self.q_start_time
        
        # BLITZ SCORING: Faster answer = More points
        if str(answer_id) == str(q.correct_answer_id):
            speed_bonus = max(0.0, (q.time_limit - time_taken) / q.time_limit)
            points = int(q.points * speed_bonus)
            self.scores[user_id] = self.scores.get(user_id, 0) + max(points, 10) # Minimum 10 points

        await self.dispatcher.broadcast(self.quiz_id, "PLAYER_ANSWERED", {"user_id": user_id})

        # BLITZ SPEED UP: If everyone answered, skip the rest of the timer!
        # (Assuming you track total players in `self.scores`)
        if len(self.current_answers) >= len(self.scores):
            if self.timer_task: self.timer_task.cancel()
            await self._evaluate()
            
        return True

    async def _evaluate(self):
        self.state = QuizState.EVALUATING
        q = self.quiz_data.questions[self.current_q_idx]
        
        await self.dispatcher.broadcast(self.quiz_id, "EVALUATING", {
            "correct_answer_id": str(q.correct_answer_id),
            "scores": self.scores
        })
        
        await asyncio.sleep(4) # Pause to show scores
        self.current_q_idx += 1
        await self._next_question()

# Global dictionary to store running quizzes
ACTIVE_QUIZZES: Dict[str, BlitzStateMachine] = {}