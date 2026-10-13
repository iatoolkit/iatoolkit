# Company Memory Wiki Schema

This wiki is the company's memory: how things are actually done here. People
explain something once (a note, a chat message, a correction, a file) and the
LLM keeps the wiki up to date. Everyone in the company reads it, and anyone can
edit a page by hand, so pages must stay readable markdown that a person can
correct.

## Core Model

- `captures` are immutable inputs saved by a person: notes, links, files,
  photos, chat messages, corrections. Each one has an author and a date.
- `pages` are markdown pages maintained by the LLM and corrected by people.
  Every change is kept in the page history and can be undone.

## Page Rules

- one page per topic or procedure ("Notas de crédito", "Despachos a regiones");
  prefer updating an existing page over creating a near-duplicate
- create a new page only when the capture introduces a clearly distinct topic
- titles are short, human-readable and stable over time
- start the page with `# Title`, then a one or two sentence overview
- write practical knowledge: steps, rules, exceptions, who decides, contacts
- **attribute every fact you add** to its author and date, at the end of the
  line or paragraph: `(Carmen Rojas, 2026-10-06)`
- keep existing content and attributions; only change what the capture changes
- when the capture contradicts the page, keep both statements with their
  attributions and mark the newer one as the current practice; never silently
  replace someone's statement
- when the capture contradicts a company document it names, say so explicitly
  ("el manual dice 30 días; en la práctica son 45")
- never invent facts that are not in the capture or already on the page
- never copy personal or sensitive data that does not serve the procedure
- write in the language of the capture

## Ingest Workflow

When a new capture arrives:

1. read the capture and its author
2. check the page index for likely existing pages
3. read the candidate pages in full
4. decide whether to update one page, create a new one, or skip
5. return the complete markdown of the resulting page
