from fastapi import FastAPI


app = FastAPI(
    title="Smart Battery Controller",
    description="API for Smart Battery Controller",
    version="1.0",
)

@app.get("/")
async def root():
    return {"status": "Servidor ativo"}

