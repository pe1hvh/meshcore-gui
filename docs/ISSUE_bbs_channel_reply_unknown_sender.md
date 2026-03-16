# BBS channel reply sent as broadcast when sender is unknown

**Component:** BBS service
**Version:** 1.14.1
**Priority:** Low
**Type:** Known Limitation

---

## Description

When a node sends `!bbs` on the BBS channel but is not yet known to the BBS node,
the help text reply is broadcast to the entire channel instead of sent privately
to the sender.

---

## Workaround

Ensure the sender has been in RF contact with the BBS node at least once before
using the BBS. Under normal operating conditions this happens automatically.

---

## Possible solution

When the BBS node receives `!bbs` from an unknown sender, reply on the channel
with a short message instructing the sender to send a direct ADVERT request first.
Once the ADVERT is received, the BBS node knows the sender's identity and can
deliver all further replies as private messages.
