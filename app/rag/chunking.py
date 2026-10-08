"""Structure-aware chunking for runbooks.

Each markdown section (## Symptoms, ## Diagnosis, ...) becomes one chunk with a stable
id like RB-003#remediation. Every chunk repeats the runbook title and services, so a
chunk still makes sense when it is retrieved on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

STEP_RE = re.compile(r"^\s*\d+\.\s*\[(low|medium|high)\]\s*(.+)$", re.IGNORECASE)
CMD_RE = re.compile(r"`([^`]+)`")


@dataclass
class RunbookStep:
    risk: str
    text: str
    commands: list[str]


@dataclass
class Chunk:
    id: str
    runbook_id: str
    title: str
    services: list[str]
    section: str
    body: str
    steps: list[RunbookStep] = field(default_factory=list)

    @property
    def text(self) -> str:
        return (f"{self.runbook_id} {self.title}\n"
                f"Services: {', '.join(self.services)}\n"
                f"Section: {self.section}\n{self.body}")

    def payload(self) -> dict:
        return {
            "chunk_id": self.id,
            "runbook_id": self.runbook_id,
            "title": self.title,
            "services": self.services,
            "section": self.section,
            "text": self.text,
        }


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_runbook(path: Path) -> list[Chunk]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].lstrip("# ").strip()
    runbook_id, _, title = header.partition("·")
    runbook_id, title = runbook_id.strip(), title.strip()
    services: list[str] = []
    meta: list[str] = []
    chunks: list[Chunk] = []
    section, body = None, []

    def flush() -> None:
        if section is None:
            return
        text = "\n".join(body).strip()
        steps = []
        for line in body:
            m = STEP_RE.match(line)
            if m:
                steps.append(RunbookStep(risk=m.group(1).lower(), text=m.group(2).strip(),
                                         commands=CMD_RE.findall(m.group(2))))
        chunks.append(Chunk(id=f"{runbook_id}#{slug(section)}", runbook_id=runbook_id, title=title,
                            services=services, section=section, body=text, steps=steps))

    for line in lines[1:]:
        if line.startswith("## "):
            flush()
            section, body = line[3:].strip(), []
        elif section is None:
            if line.lower().startswith("services:"):
                services = [s.strip() for s in line.split(":", 1)[1].split(",") if s.strip()]
            elif line.strip():
                meta.append(line.strip())
        else:
            body.append(line)
    flush()
    # Severity hint and owner go into the symptoms chunk so retrieval can see them.
    for c in chunks:
        if c.section.lower() == "symptoms" and meta:
            c.body = "\n".join(meta) + "\n" + c.body
    return chunks


def load_runbooks(directory: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("RB-*.md")):
        chunks.extend(parse_runbook(path))
    return chunks


class RunbookIndex:
    """In-memory view of every runbook chunk, used by the critic as ground truth."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = {c.id: c for c in chunks}
        self.runbooks = sorted({c.runbook_id for c in chunks})

    def get(self, chunk_id: str) -> Chunk | None:
        return self.chunks.get(chunk_id)

    def chunks_for(self, runbook_id: str) -> list[Chunk]:
        return [c for c in self.chunks.values() if c.runbook_id == runbook_id]
