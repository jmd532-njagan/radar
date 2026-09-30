from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import ProjectMetadata


async def ensure_project_metadata(db, project: str, platform: str) -> None:
    """ProjectMetadata is the FK parent of every project-scoped RADAR row, so it has to exist
    before the first failure event or chat for a project — created on demand, never seeded.
    An existing row is left as is: an event carrying some other platform label must not change
    which tools the project's chats get."""
    await db.execute(
        pg_insert(ProjectMetadata)
        .values(project=project, platform=platform)
        .on_conflict_do_nothing(index_elements=["project"])
    )
