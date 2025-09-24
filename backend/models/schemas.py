from pydantic import BaseModel
from typing import List, Optional

class AddPodcastsRequest(BaseModel):
    feeds: List[str]
    latest_n: int = 20

class QueryRequest(BaseModel):
    podcast_names: List[str]  # one or many
    query: str
