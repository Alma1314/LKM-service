from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pydantic_core import core_schema
import secrets
import hashlib
import sqlite3

def initdb():
    conn = sqlite3.connect("lkm.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hpwd TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

initdb()

app = FastAPI(title="LKM-API", version="0.0.1")

class Password(str):
    def hashpwd(self) -> str:
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac("sha256", self.encode(), salt.encode(), 100000).hex()
        return f"{salt}${hashed}"

    def verifypwd(self, stored: str) -> bool:
        salt, hashed = stored.split('$')
        nhash = hashlib.pbkdf2_hmac("sha256", self.encode(), salt.encode(), 100000).hex()
        return nhash == hashed

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        return core_schema.no_info_after_validator_function(
            cls,
            handler(str),
        )

class UserRegInfo(BaseModel):
    username: str = Field(..., max_length=100)
    email: EmailStr
    password: Password = Field(..., min_length=6, max_length=100)

@app.post("/reg")
async def reg(user: UserRegInfo):
    conn = sqlite3.connect("lkm.db")
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (user.username, user.email))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code = 400, detail = "Already registerd")

    hashed = user.password.hashpwd()
    cursor.execute(
        "INSERT INTO users (username, email, hpwd) VALUES (?, ?, ?)",
        (user.username, user.email, hashed)
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    return {"code": 0, "msg": "Registered.", "user_id": user_id}


@app.get("/")
async def root():
    return {"message": "Test"}
