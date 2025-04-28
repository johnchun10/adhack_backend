from fastapi import APIRouter

router = APIRouter(prefix="/example")

@router.get("/")
async def example_route():
    return {"message": "This is an example route from the routes folder."}
