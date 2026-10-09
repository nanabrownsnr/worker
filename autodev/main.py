import uvicorn

from .app import app
from .config import Settings

if __name__ == "__main__":
    s=Settings(); uvicorn.run(app,host=s.bind_host,port=s.port)
