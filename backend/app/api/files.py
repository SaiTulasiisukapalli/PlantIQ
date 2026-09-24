from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import File, Organization
from app.schemas.file import FileCreate, FileResponse


router = APIRouter(
    prefix="/files",
    tags=["Files"],
)


@router.post(
    "",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_file(
    file: FileCreate,
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, file.org_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    new_file = File(
        org_id=file.org_id,
        kind=file.kind,
        path=file.path,
        original_name=file.original_name,
        size_bytes=file.size_bytes,
        created_by=file.created_by,
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return new_file


@router.get(
    "",
    response_model=list[FileResponse],
)
def get_files(
    org_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    query = select(File)

    if org_id is not None:
        query = query.where(
            File.org_id == org_id
        )

    query = query.order_by(File.created_at.desc())

    result = db.execute(query)

    return result.scalars().all()


@router.get(
    "/{file_id}",
    response_model=FileResponse,
)
def get_file(
    file_id: UUID,
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)

    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    return file