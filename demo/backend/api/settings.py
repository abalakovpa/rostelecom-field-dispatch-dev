import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

@dataclass(frozen=True)
class Settings:
    source: str = 'postgres'
    host: str = '127.0.0.1'
    port: int = 5434
    database: str = 'dispatcher_next'
    user: str = 'dispatcher'
    password: str = ''

    @classmethod
    def from_env(cls):
        source=os.getenv('DATA_SOURCE','postgres')
        if source not in ('postgres','demo'):
            raise ValueError('DATA_SOURCE must be postgres or demo')
        return cls(source=source,host=os.getenv('POSTGRES_HOST','127.0.0.1'),
            port=int(os.getenv('POSTGRES_PORT','5434')),database=os.getenv('POSTGRES_DB','dispatcher_next'),
            user=os.getenv('POSTGRES_USER','dispatcher'),password=os.getenv('POSTGRES_PASSWORD',''))
