from typing import Any, List, Literal, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel
from sqlmodel import Relationship, SQLModel, Field
from nanoid import generate
from sqlalchemy import Column, JSON
from sqlalchemy.types import TypeDecorator

def short_uuid():
    return generate("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 7)

class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True)
    password_hash: str
    team_id: Optional[UUID] = Field(default=None, foreign_key="team.id")
    team: Optional["Team"] = Relationship(back_populates="users")

class Team(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    users: List[User] = Relationship(back_populates="team")

class Answer(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    text: Optional[str] = None

class Question(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    text: str
    variants: List[Answer]
    time_limit: int = 60 # in seconds
    points: int = 100 # maximum given points
    correct_answer_id: UUID

class QuestionWithoutAnswer(Question):
    correct_answer_id: UUID = Field(exclude=True)
    model_config = {"from_attributes": True}

class QuestionListType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # Triggered when SAVING to the database
        if value is not None:
            # .model_dump(mode='json') safely converts the Question model and its UUIDs into a pure dictionary
            return[item.model_dump(mode='json') for item in value]
        return value

    def process_result_value(self, value, dialect):
        # Triggered when READING from the database
        if value is not None:
            # Convert the raw database dictionaries back into Pydantic Question objects
            return [Question.model_validate(item) for item in value]
        return value
    
class Quiz(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(default_factory=short_uuid, index=True)
    questions: List[Question] = Field(default_factory=list, sa_column=Column(QuestionListType))
    synced: bool = True

class QuizWithoutAnswer(BaseModel):
    id: UUID
    code: str
    questions: List[QuestionWithoutAnswer] 
    synced: bool
    model_config = {"from_attributes": True}

class AuthRequest(BaseModel):
    username: str
    password: str

class AnswerRequest(BaseModel):
    quiz_id: UUID
    question_id: Optional[UUID] = None
    answer: Answer

class WSRequest(BaseModel):
    path: str
    body: dict

class WSResponse(BaseModel):
    type: Literal["response", "command"]
    path: Optional[str] = None  # Used for "response"
    command: Optional[str] = None  # Used for "command"
    status: int = 200
    data: Any = None
    error: Optional[str] = None

class QuizSimpleRequest(BaseModel):
    quiz_id: UUID