from typing import Type, TypeVar, List, Optional, Generic, Any
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import inspect

T = TypeVar("T", bound=SQLModel)

class DatabaseHandler(Generic[T]):
    def __init__(self, model: Type[T]):
        self.model = model
        self.url = "sqlite:///database.db"
        self.engine = create_engine(self.url)
        SQLModel.metadata.create_all(self.engine)
        
        # Get list of indexed or primary key fields for validation
        self._allowed_search_fields = {
            column.key for column in inspect(self.model).mapper.column_attrs
            if column.expression.primary_key or any(idx.name for idx in column.expression.table.indexes if column.key in idx.columns)
        }

    def get_by(self, **kwargs) -> Optional[T]:
        """
        Find a single record by field name.
        Usage: handler.get_by(username="john")
        """
        with Session(self.engine) as session:
            statement = select(self.model)
            for key, value in kwargs.items():
                # Safety check: ensure the field exists on the model
                if hasattr(self.model, key):
                    statement = statement.where(getattr(self.model, key) == value)
            
            return session.exec(statement).first()

    def get_all_where(self, **kwargs) -> List[T]:
        """Find multiple records matching criteria."""
        with Session(self.engine) as session:
            statement = select(self.model)
            for key, value in kwargs.items():
                if hasattr(self.model, key):
                    statement = statement.where(getattr(self.model, key) == value)
            return session.exec(statement).all()

    # --- Standard CRUD ---
    def save(self, instance: T) -> T:
        with Session(self.engine) as session:
            session.add(instance)
            session.commit()
            session.refresh(instance)
            return instance

    def get_all(self) -> List[T]:
        with Session(self.engine) as session:
            return session.exec(select(self.model)).all()