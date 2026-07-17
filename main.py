from fastapi import FastAPI

app = FastAPI(title="LKM-API", version="0.0.1")

@app.get("/")
async def root():
    return {"message": "Test"}
