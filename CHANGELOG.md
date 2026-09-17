# Changelog

Each entry is a spec version. The document itself is
[`print-partner-spec.md`](print-partner-spec.md); this is the short list.

## Version 2 — 17 Sep 2026

**Two new routes for telling us how a badge went** — `POST /v1/prints/{id}/printed` and `POST /v1/prints/{id}/failed` (section 8). They are optional and nothing depends on them: a `failed` report puts your reason in front of the desk staff and offers them a reprint, a `printed` report closes the badge quietly, and a client that calls neither behaves exactly as before. **An optional `pdf`** on the badge payload, alongside the unchanged `image`, for partners who would rather print vector than a bitmap; it is a per-event setting and off unless you ask for it. This version also rewrites the document in ordinary technical English and states plainly what the interface is for: printing our delegates' badges with **your** design and your kit, taking our data and, if you want it, our rendering. No field was removed or renamed.

## Version 1 — 17 Sep 2026

The first version. It gives the datagram, the pickup, the waiting list, every field and every status code, the rule that one badge is printed one time, and the test with the stand-in hub.
