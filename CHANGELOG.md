

# CHANGELOG

<!-- CHANGED: Title changed from "CHANGELOG: Message & Metadata Persistence" to "CHANGELOG" — 
     a root-level CHANGELOG.md should be project-wide, not feature-specific. -->

All notable changes to MeshCore GUI are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---


## [1.23.0] - 2026-09-01 — Repeater statistics polling

### Added
- **Periodic polling of repeater statistics.** Configured repeaters are
  logged into, queried for their status and logged out again on a
  configurable interval. Raw values are archived with the moment of
  each poll so battery voltage can be tracked over multiple days.
- `services/repeater_config_store.py` — per-device repeater
  configuration in `~/.meshcore-gui/repeaters/<device>_repeaters.json`
  (directory `0700`, file `0600`). Holds the full 32-byte public key,
  display name, login password, poll interval and enabled flag.
- `services/repeater_stats_archive.py` — append-only JSONL archive at
  `~/.meshcore-gui/archive/<device>_repeater_stats.jsonl`, one record
  per poll, with retention via the existing daily cleanup task.
- `services/repeater_poller.py` — the poll sequence itself, using
  `send_login_sync()`, `req_status_sync()` and `send_logout()`.
- `gui/panels/repeater_stats_panel.py` — read-only REPEATERS panel, one
  card per repeater showing **every** field from the last status
  response, the age of the last successful poll and the last error.
  Fields are rendered from the response itself rather than a fixed list,
  so a field a future firmware adds appears without a code change.
- `docs/examples/repeaters.json.example` — annotated example
  configuration, plus README section 8.2 covering the file location,
  the fields, the permissions and the archive format.
- `REPEATER_POLL_ENABLED`, `REPEATER_POLL_INTERVAL` (900 s),
  `REPEATER_POLL_CHECK_INTERVAL`, `REPEATER_LOGIN_TIMEOUT`,
  `REPEATER_STATUS_TIMEOUT`, `REPEATER_STATS_RETENTION_DAYS` and
  `REPEATERS_DIR` in `config.py`.

### Changed
- `_main_loop()` runs the repeater poll alongside the existing periodic
  tasks (contact refresh, key retry, cleanup, message poll), following
  the same interval-guarded pattern.
- `_cleanup_old_data()` also applies retention to the repeater statistics
  archive.

### Impact
- At most one repeater is polled per check, and each repeater gets its
  own start offset within the interval, so two repeaters are never
  queried back to back. Two repeaters on the default interval land
  roughly 7.5 minutes apart.
- A failed login, an absent status response or an exception is recorded
  as a poll attempt with `ok: false` and a reason, and does not block the
  other repeater or stop the application. Logout is always sent once a
  login has been attempted, including after a timeout.
- Values are stored exactly as the repeater reports them — no scaling,
  rounding or averaging. Battery voltage keeps the unit the firmware
  returns.
- The login password is reachable through a single method that only the
  poller calls; the objects handed to the GUI have no password field, and
  no password is written to the archive, the log or any error message.
- Polling stays idle until a repeater is configured, so an installation
  without a configuration file behaves exactly as before.
- No change to the archive JSON schema, the public API, or any existing
  public method signature. Worker and dashboard constructors gained
  optional keyword arguments only.

### Rationale
- A full 32-byte public key is required per repeater because the meshcore
  library rejects a prefix for login, status and logout requests.
- One status request per poll: every additional measurement is another
  full round trip over the radio, which costs airtime and makes the local
  node deaf for longer without adding information. Averaging belongs
  wherever the analysis happens, not here.


---


## [1.22.6] - 2026-08-31 — Queued messages no longer stall when the device notification is missed

### Fixed
- 🛠 **Incoming messages received by the radio never reached the
  application** (`ble/worker.py`): the companion radio received the packet
  and ACKed it, but no `CONTACT_MSG_RECV` event followed and the message
  was never archived or displayed. `MeshCore.start_auto_message_fetching()`
  (meshcore 2.3.9.1) is purely event-driven: `_fetch_messages_loop()` runs
  only when the device emits `messages_waiting`. There is no periodic
  fallback, so a missed notification leaves the message queued on the
  device indefinitely. Diagnosis confirmed the gap: `RX_LOG_DATA` showed a
  DIRECT `TEXT_MSG` arriving at -55 dBm followed by an outgoing ACK, while
  no `get_msg()` command was sent over the serial link for minutes and no
  traceback was logged — the fetch loop had never been started rather than
  having crashed. Restarting the node does not help, because the trigger,
  not the queue, is what goes missing.

### Added
- `MSG_POLL_INTERVAL` in `config.py` (default 30 s, `0` disables) —
  interval for the safety-net poll of the device message queue.
- `SerialWorker._poll_pending_messages()` — drains the queue by calling
  `get_msg()` until the device reports `NO_MORE_MSGS`, independently of
  the `messages_waiting` event.

### Changed
- `_main_loop()` runs the message poll alongside the existing periodic
  tasks (contact refresh, key retry, cleanup), following the same
  interval-guarded pattern.

### Impact
- Messages that the notification path misses are delayed by at most one
  poll interval instead of being lost. `start_auto_message_fetching()`
  remains active, so the event path still delivers immediately when it
  works; the poll only picks up what it leaves behind.
- Fetched messages are dispatched by the library as ordinary message
  events, so existing handlers, deduplication and archiving apply
  unchanged — messages already delivered via the event path are not
  stored twice.
- No change to the archive JSON schema and no change to any public
  method signature.

### Rationale
- A fixed-interval poll is the smallest change that closes the gap
  without reimplementing message retrieval or forking the library. The
  interval is a config constant so it can be tuned per deployment, or
  switched off entirely once the underlying notification proves reliable.

### Known limitation
- Room Server history messages still carry their **receive** time rather
  than their original send time: `EventHandler.on_contact_msg()` calls
  `Message.incoming()` without `time=` / `date=`, so a message replayed
  from server history is dated at the moment it arrives. Confirmed
  against the archive, where a message sent on 2026-08-27 is stored as
  `2026-08-31 07:10:57`. Not fixed here: whether the
  `CONTACT_MSG_RECV` payload carries a usable original timestamp cannot
  be determined until room traffic flows again, and guessing at the field
  would be a fix without a confirmed root cause.

---


## [1.22.5] - 2026-08-31 — Failed channel discovery no longer erases the channel list

### Fixed
- 🛠 **All channels except Public disappeared after a reboot**
  (`ble/worker.py`, `services/channel_discovery.py`): `_discover_channels()`
  persisted its result unconditionally. When the device returned ERROR on
  every probed slot, the scan aborted, fell back to
  `[{"idx": 0, "name": "Public"}]`, and wrote that single entry over the
  cached channel names — `DeviceCache.set_channel_names()` replaces the
  whole mapping rather than merging into it. Because
  `CHANNEL_CACHE_ENABLED` is off by default, those names are the only
  channel source at startup, so the loss was permanent and took out both
  the Messages and the Archive submenu, which share one `data['channels']`
  source. The observed failure left nine cached channel *keys* intact
  (written per index) beside a single cached *name*.

### Added
- `services/channel_discovery.py` — `ChannelDiscoveryResult` dataclass
  plus `merge_with_cached_names()`, `name_map_to_channels()` and
  `stale_key_indices()`. Pure data transformation, no I/O.

### Changed
- Channel discovery now records which slots the device answered for and
  merges that result into the cached names instead of replacing them.
  A slot answered with a name is stored, a slot answered without one is
  dropped (so channels deleted on the device do not come back), and a
  slot that timed out or returned ERROR keeps its cached name.
- Stale-key cleanup replaces the `len(discovered) >= 2` heuristic with
  the same rule: a cached key is only removed when the device
  authoritatively reported its slot as vacant.
- The `Public`-only fallback now applies solely when the device confirmed
  nothing *and* no cached names exist.
- `CHANNEL_DISCOVERY_ABORT_THRESHOLD` (default 3) replaces the hardcoded
  consecutive-error limit in `config.py`.

### Impact
- No public method signature changed; `_discover_channels()` keeps its
  `async def (self) -> None` contract and the cache JSON schema is
  untouched.
- A failed scan now leaves `SharedData.channels` populated from cache
  rather than collapsing it to Public, so the drawer submenus, the send
  selector, the channel backup (which reads the same cached names) and
  hashtag key derivation all survive an unresponsive device.
- Channel deletion on the device still propagates: an empty slot the
  device confirms is authoritative and removes both name and key.
- Decryption keys are no longer dropped on a failed scan, so messages on
  channels the device did not confirm remain decodable.
- `VERSION` bumped `1.22.4` → `1.22.5` (PATCH: backwards-compatible
  bugfix).

### Rationale
The existing safety net carried the right intent — its comment reads
"so a transient discovery failure does not wipe the cache" — but guarded
only the key cleanup, leaving the name write above it exposed. The
underlying defect is that the code could not tell "the device says this
slot is empty" apart from "the device said nothing"; both ended as an
absent entry in `discovered`. Recording answered slots makes that
distinction explicit and lets one rule serve both the names and the
keys, rather than adding a second heuristic on top of the first.

---

## [1.22.4] - 2026-08-16 — Main-page send selector follows the active channel

### Fixed
- 🛠 **Send selector on the dashboard stayed on Public regardless of the
  channel being viewed** (`gui/panels/messages_panel.py`):  selecting a
  channel in the drawer submenu routes through
  `MessagesPanel.set_active_channel()`, which filtered the message list
  and rewrote the header label but never touched the send selector.
  `update_channel_options()` did not compensate: its corrective branch
  (`if self._channel_select.value not in opts`) only fires for a value
  that has disappeared from the options, and `0` (Public) is always
  present.  Viewing `#noodnet-ov` and pressing Send therefore published
  on Public.  `set_active_channel()` now points the selector at the
  active channel via the new `_sync_send_channel()` helper.

### Impact
- The sync is applied at most once per drawer selection.
  `set_active_channel()` is re-invoked from `update_filters()` on every
  500 ms dashboard tick, so an unconditional sync would overwrite a
  manual selector choice twice per second; a pending flag, raised only
  when the active channel actually changes, prevents that.  The flag
  stays raised while the channel is absent from the options, so the
  sync retries on a later tick — this covers page load with
  `?panel=messages&channel=N`, where `set_active_channel()` runs before
  the options are populated.
- The 'All' (`None`) and 'DM' (`'DM'`) views leave the selector
  untouched: neither is a valid send target, and `'DM'` is not an
  option key.  A channel index missing from the options likewise leaves
  the current selection intact instead of falling back to Public.
- No public method signature changed; `_sync_send_channel()` is private
  and `set_active_channel()` keeps its contract.
- `VERSION` bumped `1.22.3` → `1.22.4` (PATCH: backwards-compatible
  bugfix).

### Rationale
1.22.3 fixed the reply selector on the route page but not this one —
the bug report's phrase "klik ik vanuit #noodnet-ov" refers to the
drawer submenu on the main page, where a second, independent selector
lives (the send row that moved from `InputPanel` into `MessagesPanel`).
The drawer is the only place that knows which channel the user is
looking at, so `set_active_channel()` is the correct place to keep the
selector in step; deriving it anywhere else would reintroduce the
list-position guesswork that caused the original mis-sends.

---


## [1.22.3] - 2026-08-16 — Reply defaults to the message's own channel + dated message timestamps

### Fixed
- 🛠 **Route page reply select ignored the message's channel**
  (`gui/route_page.py`):  `_render_send_panel` derived its default from
  the *position* in the channel list (`data['channels'][0]['idx']`,
  normally Public) instead of from the message the page was opened for.
  Opening the route of a `#noodnet-ov` message and pressing Send without
  touching the select therefore published the reply on the wrong
  channel.  The default now comes from `msg.channel` via the new
  `_default_reply_channel()` helper, which falls back to the first
  available channel for DMs (`channel is None`) and for channel indices
  that are no longer present on the device — a slot can be vacated by
  the post-discovery cache sync added in 1.22.2.

### Added
- ✨ **`Message.date` field** (`core/models.py`):  local date as
  `YYYY-MM-DD`, populated by `Message.incoming()` and
  `Message.outgoing()`.  Declared last in the dataclass so positional
  construction stays backward-compatible, and defaulted to `""` so
  existing callers are unaffected.
- ✨ **`Message.now_date()` and `Message.display_timestamp()`**
  (`core/models.py`):  `display_timestamp()` is the single formatting
  authority for message timestamps — it returns
  `YYYY-MM-DD HH:MM:SS` when the date is known and degrades to the bare
  `HH:MM:SS` when it is not.
- ✨ **`date` persisted in the message archive**
  (`services/message_archive.py`):  `add_message` writes the field
  alongside `time` and `timestamp_utc`.

### Changed
- 🔄 **Message lines now show the date before the time**
  (`core/models.py`, `gui/route_page.py`,
  `gui/panels/room_server_panel.py`):  `Message.format_line()` opens
  with `display_timestamp()`, so the dashboard messages panel and the
  archive page pick the change up automatically.  The route page
  message-info header and the room-server message list, which format
  their own lines, were switched to the same helper for consistency.

### Impact
- Archive JSON gains one field; the schema stays additive, so older
  archives load unchanged and the domca.nl collector is unaffected.
  Entries written before this release carry no `date`, so
  `Message.from_dict()` derives one from `timestamp_utc`, converted to
  local time so it matches the local `time` field across midnight.
  When `timestamp_utc` is absent or unparseable the date stays empty and
  the line renders exactly as it did in 1.22.2.
- Message display lines are ~11 characters wider.  No public method
  signature changed; `Message.incoming()` gained an optional
  keyword-only `date` parameter.
- `VERSION` bumped `1.22.2` → `1.22.3` (PATCH: backwards-compatible
  bugfix plus an additive, defaulted model field).

### Rationale
The reply select is on a page that exists to show *one specific*
message, so the message — not the channel list ordering — is the correct
source for the default; deriving it from list position was a latent
mis-send waiting to happen.  For the timestamp, the date could not be
shown by editing a label: `Message` simply had no date, because
`now_timestamp()` produces `HH:MM:SS` only.  The date existed solely as
`timestamp_utc` in the archive layer and was not read back by
`from_dict()`.  Adding a first-class `date` field fixes the cause rather
than papering over it at each render site, and routing every render site
through `display_timestamp()` keeps the format in one place.

---


## [1.22.2] - 2026-05-04 — Backup honors live channel set + post-discovery cache cleanup

### Fixed
- 🛠 **Channel backup exported empty-name slots** (`services/channel_backup_store.py`):
  `export_from_cache` built its index list from the union of cached
  channel names and cached PSKs.  On a device with `MAX_GROUP_CHANNELS=100`
  firmware-initialised slots, the cache could hold up to 100 PSKs while
  only 3 slots were actually named — producing a backup file with 97
  empty-name entries that contradicted the dialog's promise ("This
  device reports 3 active channels").  The export now uses the
  named-slot set (`name_by_idx`) as the sole authority for which slots
  to write; PSKs continue to be looked up from cache, but only for
  named slots.
- 🛠 **PacketDecoder accumulated stale keys across sessions**
  (`ble/worker.py`, `ble/packet_decoder.py`):  `_discover_channels` now
  performs a post-discovery sync that drops any cache entry and any
  decoder mapping for slots that did not appear in the discovered
  channel set.  Without this, brute-force key matching ran across all
  100 keys per packet and could mis-route messages to vacated slot
  indices, which in turn caused the bot's channel guard to silently
  reject legitimate replies (the symptom previously workaround-fixed
  by manually wiping `~/.meshcore-gui/cache/`).  A safety net skips
  the sync when fewer than two channels were discovered, so a
  transient discovery failure (which falls back to the Public-only
  list) does not wipe the cache.

### Added
- **`PacketDecoder.remove_channel_key(channel_idx)`**
  (`ble/packet_decoder.py`):  removes every registered secret whose
  mapping points at the given index.  Used by the post-discovery sync;
  also available for future delete/move flows that want to evict keys
  from the in-memory decoder without waiting for the next discovery.

### Changed
- `VERSION` bumped `1.22.1` → `1.22.2` (PATCH: backwards-compatible
  bug fix).

### Impact
- Existing on-disk cache files are not migrated automatically; the
  first successful discovery after upgrading will prune stale entries
  in place.
- Backup files written by 1.22.1 that contain empty-name entries
  remain readable by Restore — `diff_against_device` still classifies
  empty-PSK entries as `skipped`, so no destructive change happens on
  re-import.
- No public API or BLE protocol changes.  No GUI panel changes.  The
  bot, BBS, channel-add/move/delete flows, REST API, and `domca.nl`
  ingest are untouched.

### Rationale
The dialog text already advertised "every channel currently known to
this GUI" but the implementation broadcast PSK presence as proof of
existence, leading to silent divergence between what the dialog
promised and what the file contained.  The cache-cleanup half of the
fix removes the underlying source of that divergence and, as a side
effect, eliminates the brute-force decoder pollution that was the
root cause of the bot-not-replying behaviour observed before manual
cache wipes.

---


## [1.22.1] - 2026-04-27

### Added
- **JSONL stream output for the RX log** (`services/message_archive.py`):
  Every received LoRa packet is now also written immediately to an
  append-only JSON Lines file at
  `~/.meshcore-gui/archive/<device>_rxlog.jsonl`, one JSON object per
  line. This provides a real-time data source for separate local
  services (such as `meshcore-watchlist`) that want to consume the raw
  RX feed without depending on the GUI's internal batched JSON file
  format.

  - The new file lives alongside the existing `<device>_rxlog.json`.
    The original batched archive (60 s flush interval, atomic rewrite)
    is unchanged so the GUI, the public REST API and `domca.nl` keep
    working without modification.
  - Writes are direct (no buffer) so end-to-end latency from radio
    reception to JSONL line is sub-second, suitable for live
    monitoring use cases.
  - A failure on the JSONL append path is logged via `debug_print` and
    does not affect the buffered JSON archive — the two paths are
    independent.

### Changed
- `_cleanup_rxlog()` now also rewrites the JSONL stream file to drop
  entries older than `RXLOG_RETENTION_DAYS`. Same retention policy as
  the existing JSON archive; corrupt lines (e.g. a partial last line
  after a crash) are skipped during cleanup.
- `VERSION` bumped `1.22.0` → `1.22.1` (PATCH: additive feature, fully
  backwards-compatible).

### Impact
- No BLE/worker changes; SharedData and the BLE command pipeline are
  untouched.
- No public REST API changes; `domca.nl` ingest is unaffected.
- Existing consumers of `<device>_rxlog.json` see no difference.
- Disk usage increases modestly (one additional file per device,
  same retention window). On a Raspberry Pi 5 with SSD the extra
  per-packet I/O is negligible.

---


## [1.22.0] - 2026-04-21

### Added
- **Drawer channel-list sort toggle** (`services/channel_sort_store.py`,
  `services/channel_service.py`, `gui/dashboard.py`):
  The drawer Messages and Archive submenus can now be sorted either by
  channel index (the native MeshCore order, default) or alphabetically
  by channel name. The choice is exposed as a single sub-button per
  submenu labelled `↕ Sort: index` / `↕ Sort: name` and is shared
  between both submenus so a single click reorders both lists at once.

  - New store `ChannelSortStore` persists the preference to
    `~/.meshcore-gui/channel_sort.json` so it survives application
    restarts. The store is global (not per-device) because the sort
    mode is a pure UI concern.
  - New pure helper `sort_channels(channels, mode)` in
    `services/channel_service.py`. The Public channel (`idx == 0`) is
    always pinned to the top regardless of mode; moving it during an
    alphabetical sort would be confusing as it is the default broadcast
    slot. Sort-by-name is case-insensitive (`str.casefold`).
  - The dashboard submenu fingerprint now includes the sort mode so a
    user-initiated toggle forces a rebuild even when the channel list
    itself has not changed. After toggling, the dashboard calls
    `_update_submenus` immediately with a fresh SharedData snapshot so
    the reorder is visible without waiting for the next 500 ms tick.

### Changed
- `CHANNEL_SORT_MODE_DEFAULT` added to `config.py` as the factory
  default for the sort mode (``"index"``). Used by `ChannelSortStore`
  on first run and when the stored file is missing or contains an
  invalid value.
- `VERSION` bumped `1.21.0` → `1.22.0` (MINOR: new backwards-compatible
  feature).

### Impact
- No BLE/worker changes; SharedData and the BLE command pipeline are
  untouched.
- The `ChannelPanel` Move/Reindex dropdown is intentionally NOT
  affected — that list is an admin tool for operators who know which
  slot they want, not a navigation aid.
- The (unused but still present) `FilterPanel` is not touched.
- Existing drawer submenu functionality — delete/move per-channel
  buttons, Add/Backup/Restore buttons, DM and ALL entries — is
  preserved unchanged.

### Rationale
Operators with a large number of channels reported needing a way to
find a specific channel quickly. Index order is fine for small
deployments but becomes unwieldy above ~10 channels. Alphabetical
order provides a predictable scan path; keeping Public pinned at the
top preserves the mental model of "slot 0 is the broadcast channel".
Persistence across restarts avoids forcing the user to re-select the
preferred order every session.


---


### Added
- **Local channel backup & restore** (`services/channel_backup_store.py`,
  `gui/panels/channel_backup_panel.py`):
  Channels can now be snapshotted to a local JSON file and restored after
  a firmware reflash, NVS erase or device replacement. The operator no
  longer needs to externally note down each slot's PSK before flashing.

  - New store `ChannelBackupStore` writes to
    `~/.meshcore-gui/channel_backups/_<safe_dev_id>_channels.json`,
    mirroring the `BotConfigStore` / `PinStore` per-device filename
    convention so multiple nodes coexist without conflict.
  - Data is sourced exclusively from `DeviceCache`
    (`channel_keys` + `channel_names`) plus the live channel snapshot
    from `SharedData`. No new BLE/serial protocol calls are introduced
    — restore reuses the existing `add_channel` command handler via
    the worker command queue.
  - On-disk schema: `{schema_version, device_id, firmware_version,
    exported_at, channels: [{slot_idx, name, psk_hex}]}`. Schema version
    is pinned at `1`; `ChannelBackupStore._parse()` rejects unknown
    versions so older clients fail fast when the format changes.
  - The schema is intentionally distinct from the public REST API's
    channel payload: backups include every slot (public, hashtag, and
    private) because local recovery is the whole point, while
    `public_api_service` continues to filter out private channels as
    before. Backup files never leave `~/.meshcore-gui/` and are not
    exposed by the API route layer.
  - New panel `ChannelBackupPanel` adds two dialogs accessed from the
    Messages submenu:
    - **💾 Backup Channels** — one-click export with pre/post summary
      showing how many slots were written and, critically, how many had
      no cached PSK (those cannot be restored without manual input —
      the dialog surfaces the count so the operator is not caught out).
    - **📥 Restore Channels** — loads the device's own backup file by
      default, or an uploaded `.json` file for cross-device restores
      (e.g. migrating from an old Heltec V3 to a new one after
      firmware flashing). Entries are classified into
      `restorable` / `conflict` / `identical` / `skipped` buckets
      **before** any device write happens, so the operator sees in
      advance which slots will be overwritten and which have no PSK.
      Confirm dispatches one `add_channel` command per entry through
      the normal worker queue.

### Changed
- `gui/dashboard.py`: `DashboardPage.__init__` now accepts an optional
  `device_id` parameter (default `""`). This is threaded through to
  `ChannelBackupPanel` so the backup store can namespace its file to
  the correct node. All existing call sites were updated; the
  parameter is keyword-compatible so external callers that did not
  supply it continue to work unchanged.
- `__main__.py`: added module-level `_device_id` so the `@ui.page('/')`
  handler (which recreates `DashboardPage` per client session) can
  pass the device identifier into the dashboard constructor.
- `config.py`: version bump `1.20.2 → 1.21.0`.

### Not changed (deliberately out of scope)
- No automatic or scheduled backups — the operator triggers a backup
  explicitly before risky operations. Auto-backup on channel changes
  was considered and deferred; the cache already persists channel
  keys on every write, so an on-demand export is sufficient.
- No cloud/remote storage and no integration with `domca.nl`. Backup
  files contain private channel PSKs and are therefore strictly local.
- No new BLE/serial commands. Restore is purely a replay of existing
  `add_channel` operations; the firmware is unaware that a bulk
  restore is happening.

---


## [1.20.2] - 2026-04-19

### Fixed
- **Public API omitted `sender_pubkey` and `path_names` from the message payload**
  (`services/public_api_service.py`):
  `get_messages_payload()` built each item dict with `sender`, `text`,
  `timestamp`, `hops` and `path_hashes`, but silently dropped the already-
  resolved `sender_pubkey` and `path_names` fields that `BleEventHandler`
  writes to every archived message (see `_resolve_path_names()` in
  `ble/events.py` and the archive schema in `services/message_archive.py`
  lines 135–137). Downstream consumers were therefore forced to re-resolve
  path hashes themselves using only the 1-byte path-hash prefix — a lookup
  that collides heavily in networks with more than ~256 nodes and yields
  the wrong repeater name, type and coordinates on nearly every hop. The
  `sender_pubkey` omission had a similar effect on the sender column:
  clients could only match on display-name, which is ambiguous when two
  nodes share a name stem (e.g. `NL-OV-ZWO-LGH-PD5WB` vs the mobile
  variant `NL-OV-ZWO-LGH-PD5WB-MOB`).
  Fix: added `"sender_pubkey"` and `"path_names"` to the item dict. Both
  fields are read straight from the archive — no new resolution logic is
  introduced, so there is no additional cost on the hot path. The response
  schema change is additive: existing clients that ignore unknown keys
  continue to work unchanged.

### Changed
- `config.py`: version bump `1.20.1 → 1.20.2`.

---

## [1.20.1] - 2026-04-15

### Fixed
- **Bot global cooldown blocked all senders** (`services/bot.py`):
  `_last_reply` was a single float, so a reply to any node would start a
  5-second silence window for *all* other nodes. During testing with multiple
  contacts, only the first `#test` message received a bot reply; subsequent
  messages from different senders were silently dropped by Guard 5.
  Fix: replaced `_last_reply: float` with `_last_reply_per_sender: Dict[str, float]`.
  Each sender now has an independent cooldown window; a reply to one node
  does not affect any other node. LRU eviction caps the dict at 200 entries
  to prevent unbounded memory growth in long-running sessions.

- **Bot deaf on first run when no channels saved** (`services/bot.py`):
  `_get_active_channels()` returned an empty frozenset when `BotConfigStore`
  had no saved channel selection (i.e. the user had never clicked
  "💾 Save channels"). The bot was therefore silent on all channels despite
  the BOT panel showing all channels pre-checked. The `BotSettings.channels`
  docstring already documented this as the intended fallback case, but the
  code did not implement it.
  Fix: `_get_active_channels()` now falls back to `BotConfig.channels`
  (`{1, 4}` — `#test` and `#bot`) when the stored set is empty, matching
  the documented intent.

---

## [1.20.0] - 2026-04-10

### Changed
- `services/device_identity.py`: `device_identity.json` upgraded from v1
  (single flat object) to v2 (dict keyed by `source_device`).  Multiple
  GUI instances running on different serial ports (e.g. `/dev/ttyUSB0` and
  `/dev/ttyUSB1`) each write their own entry without overwriting each other.
- `write_device_identity()` now reads the existing file before writing,
  updating only the entry for the current `source_device`.
- `read_device_identity()` accepts an optional `source_device` parameter:
  returns a single entry dict when specified, or the full multi-device dict
  when called without arguments.
- `_load_raw()` (internal) handles v1 → v2 migration transparently on first
  write: the old flat object is re-keyed under its `source_device` value.
- Console output now includes the device path:
  `📝 Device identity saved → ~/.meshcore-gui/device_identity.json [/dev/ttyUSB1]`.
- No changes to `ble/worker.py` or any other module — API is fully backward
  compatible.

## [1.19.0] - 2026-04-06

### FIXED
- **Wrong channel attribution for hashtag channels** (`ble/packet_decoder.py`):
  `ChannelCrypto.calculate_channel_hash()` produces a different channel identifier
  than what the MeshCore firmware embeds in packets, causing `_hash_to_idx` to
  return `None` for all hashtag-channel messages. As a result, `on_channel_msg`
  fell back to the `channel_idx` from the `CHANNEL_MSG_RECV` event — which was
  itself incorrect — and messages sent on `#mc-radar` appeared in `#weather` and
  vice versa.
  Fix: brute-force channel resolution. When the hash lookup returns `None`, every
  registered key is tried individually via a single-key keystore. The first key
  that produces a valid decryption determines the channel index. The result is
  cached in `_hash_to_idx` for O(1) resolution on all subsequent packets for that
  channel.

- **Cross-channel message duplication** (`ble/events.py`):
  A second copy of the same physical packet was stored under a different channel
  index because two independent dedup guards both failed simultaneously: (1) the
  `message_hash` from `meshcoredecoder` differed from the one in the
  `CHANNEL_MSG_RECV` event payload (two separate libraries), breaking hash-based
  dedup; (2) the `channel_idx` resolved by `PacketDecoder` differed from the
  `channel_idx` reported by the event, breaking content-based dedup.
  Fix: when `on_rx_log` successfully stores a message, it now also marks a
  channel-agnostic sentinel key (`'*'`) in `DualDeduplicator`. `on_channel_msg`
  checks this sentinel before storing and suppresses the message if set, regardless
  of hash or channel_idx differences between the two systems.

- **Empty `path_hashes` on hashtag channels** (`ble/events.py`):
  `_path_cache` is keyed by the `message_hash` from `meshcoredecoder`, but
  `on_channel_msg` performed the lookup with the `message_hash` from `meshcore`
  (different value), causing `_path_cache.pop()` to always return `[]`.
  Fix: secondary `_path_cache_by_content` keyed by `"sender:text[:100]"` as
  fallback. Path hashes are now recovered even when the two hash values disagree.

- **Stale channel key in cache after `del_channel` reindex** (`ble/commands.py`,
  `services/cache.py`): After moving a channel slot from `old_idx` to `new_idx`,
  the cache entry for `old_idx` was never removed. On the next startup, both the
  old and the new index had the same secret, causing the same channel to appear
  twice in the cache and the last channel not to be displayed.
  Fix: new `DeviceCache.remove_channel_key(idx)` method; called after each slot
  move in `_cmd_del_channel`. Added `asyncio.sleep(0.5)` before re-discovery to
  let the device commit all slot changes before `_discover_channels` reads them.

### ADDED
- **Channel Move / Reindex** (`gui/panels/channel_panel.py`, `ble/commands.py`,
  `gui/dashboard.py`): New mode `↕️ Move / Reindex` in the Channel Manager dialog.
  The user selects a source channel from a dropdown and a target index from the
  number field. A `↕` button appears inline next to `🗑` for each channel in both
  the Messages and Archive submenus.
  `_cmd_move_channel` reads the channel secret from `DeviceCache` (or fetches it
  directly from the device as fallback), writes to the new slot, clears the old
  slot, and updates both cache entries atomically before triggering re-discovery.

### CHANGED
- `gui/panels/channel_panel.py`: Dialog title changed from `📡 Add Channel` to
  `📡 Channel Manager`; submit button renamed from `Add Channel` to `Confirm`.
- `gui/dashboard.py`: `_make_channel_sub_item()` extended with `on_move` callback
  and inline `↕` button; both Messages and Archive submenus pass the callback.
- `config.py`: version bump `1.18.1 → 1.19.0`.

### IMPACT
- `ble/packet_decoder.py`: `_secret_to_idx` dict added; `_resolve_channel_by_brute_force()`
  helper added; fallback invoked in `decode()` when hash lookup fails. O(n_channels)
  cost on first packet per channel; O(1) thereafter.
- `ble/events.py`: `_path_cache_by_content` dict added; sentinel mark added in
  `on_rx_log`; sentinel check and content-key path fallback added in `on_channel_msg`.
- `ble/commands.py`: `move_channel` registered in handler dict; `_cmd_move_channel()`
  added; `_cmd_del_channel()` calls `remove_channel_key()` and includes settle delay.
- `services/cache.py`: `remove_channel_key(idx)` added — no-op when key absent.
- `gui/panels/channel_panel.py`: `_move_section`, `_move_select` widgets added;
  `open()` accepts `mode` and `preselect_idx` parameters; `_submit_move()` added.
- `gui/dashboard.py`: `_make_channel_sub_item()` signature extended with `on_move`.

---

## [1.18.1] - 2026-04-05

### FIXED
- **Drawer width** (`gui/dashboard.py`): increased from 300 px to 360 px so that
  longer channel names such as `[19] #radio-zend-amateurs` fit without truncation.
- **`del_channel` library fallback** (`ble/commands.py`): `_cmd_del_channel` now
  catches `AttributeError` when `mc.commands.del_channel()` is not available in
  the installed pymeshcore version and falls back to overwriting the slot with an
  empty name via `set_channel(idx, '', None)`, which the firmware treats as removal.
- **Delete confirmation dialog** (`gui/dashboard.py`): clicking 🗑 now opens an
  "Are you sure?" dialog (Cancel / Delete) before dispatching the `del_channel`
  command, preventing accidental removals.

### CHANGED
- `config.py`: version bump `1.18.0 → 1.18.1`.

---

## [1.18.0] - 2026-04-05

### ADDED
- **Channel delete button** (`gui/dashboard.py`): each channel entry in the
  MESSAGES and ARCHIVE submenus now shows an inline 🗑 delete button next to
  the channel name. Clicking it queues a `del_channel` command for the BLE
  worker without requiring any additional confirmation dialog.
- **`del_channel` command handler** (`ble/commands.py`): new
  `_cmd_del_channel()` async method that deletes the target channel slot via
  `mc.commands.del_channel(idx)` and then re-indexes all higher-numbered
  channels by one position using `set_channel` + `del_channel`. Secrets for
  private channels are read from the `DeviceCache` so no key material is lost
  during renumbering. A full channel re-discovery is triggered afterwards via
  `_load_data_callback()`.

### CHANGED
- **Drawer width** (`gui/dashboard.py`): left navigation panel widened from
  260 px to 300 px (min-width 200 px → 220 px) for better readability of
  channel names.
- `config.py`: version bump `1.17.1 → 1.18.0`.

### IMPACT
- `gui/dashboard.py`: new static method `_make_channel_sub_item()`;
  `_update_submenus()` uses it instead of `_make_sub_btn()` for channel rows.
  All existing submenu logic (ALL, DM, ＋ Add Channel, rooms) is unchanged.
- `ble/commands.py`: one new handler registered; no existing handlers touched.

### RATIONALE
- Users need a quick way to remove channels directly from the navigation menu
  without opening a separate dialog.
- Re-indexing keeps the channel list compact (no sparse gaps) which matches
  MeshCore firmware expectations and the visual convention of sequential indices.

---

## [1.17.1] - 2026-04-04

### FIXED
- **Multibyte path hash support** (`ble/events.py`, `core/shared_data.py`):
  corrected docstrings in both `_resolve_path_names` methods that incorrectly
  described path hashes as "2-char hex strings". The actual contact lookup
  uses `startswith` matching, which is hash-size agnostic and correctly
  handles 1-byte (2 hex chars), 2-byte (4 hex chars) and 3-byte (6 hex chars)
  path hashes as introduced in MeshCore firmware v1.14.0. No functional code
  was changed — only the documentation was incorrect.
- **MariaDB schema** (`meshcore_schema.sql`): `meshcore_messages.path_hashes`
  column widened from `VARCHAR(128)` to `VARCHAR(255)`. The old limit caused
  silent truncation for paths longer than ~40 hops in 1-byte mode or ~25 hops
  in 2-byte mode. Migration is backward-compatible; existing data is unchanged.

### CHANGED
- `config.py`: version bump `1.17.0 → 1.17.1`.

### RATIONALE
- MeshCore firmware v1.14.0 (2026-03-06) introduced configurable path hash
  sizes (1-, 2- or 3-byte per repeater). Verification confirmed that
  `meshcoredecoder 0.3.2` already returns correctly sized hex strings via
  `_decode_path_len_byte`. The GUI path-resolution logic was already
  forward-compatible; only the docstrings and the MariaDB column width required
  correction.

### IMPACT
- No BLE handler, GUI panel, service or API endpoint modified.
- `meshcoredecoder` library unchanged; no pip update required.
- MariaDB migration: single `ALTER TABLE` statement, no downtime, no data loss.

---

## [1.17.0] - 2026-04-04

### ADDED
- **Public REST API** (`api/routes.py`, `api/__init__.py`): four read-only
  GET endpoints registered on the NiceGUI/FastAPI application instance.
  Enabled via `API_ENABLED = True` in `config.py` (default: on).
  - `GET /api/v1/stats` — aggregate statistics for the last 72 hours:
    total messages, unique senders, active nodes per type, average hops
    and peak hour. Only public and hashtag channel messages are counted.
  - `GET /api/v1/nodes` — full contact list with node type, GPS coordinates
    and (when available) last-seen timestamp and battery voltage.
  - `GET /api/v1/messages?limit=N&offset=N` — paginated message list
    restricted to public (idx 0) and hashtag (`name.startswith('#')`)
    channels. Private channel messages are unconditionally excluded.
  - `GET /api/v1/channels` — channel list with `is_private` flag per entry.
- **PublicApiService** (`services/public_api_service.py`): pure-Python
  business logic for all four endpoints.  Contains the single source of
  truth for channel-type classification (`is_public_channel`,
  `is_private_channel`) used throughout the API layer.
- **`API_ENABLED`** and **`API_CORS_ORIGINS`** constants (`config.py`):
  toggle the API on/off and configure allowed CORS origins.

### CHANGED
- `config.py`: version bump `1.16.0 → 1.17.0`; `PUBLIC API` section added
  with `API_ENABLED` and `API_CORS_ORIGINS`.
- `__main__.py`: conditional `register_routes(_shared)` call after
  `SharedData` construction; prints API URL or disabled notice at startup.

### RATIONALE
- Enables the domca.nl PHP collector to pull live mesh data over HTTP
  without direct access to the SQLite archive or SharedData internals.
- Filtering is enforced server-side: what is not public can never leak,
  even without authentication.

### IMPACT
- No existing route, panel or BLE handler modified.
- `SharedData` and `MessageArchive` accessed read-only.
- Zero breaking changes to v1.16.0 behaviour when `API_ENABLED = False`.

---

## [1.16.0] - 2026-04-04

### ADDED
- **Add Channel dialog** (`gui/panels/channel_panel.py`): new `ChannelPanel` class
  that renders a `ui.dialog` with three modes — Hashtag, Private New, and
  Private Existing — accessible via a `＋ Add Channel` button at the bottom of
  the Messages submenu.
- **ChannelService** (`services/channel_service.py`): pure-Python business logic
  for channel key management. Provides `generate_secret()`, `derive_hashtag_key()`,
  `build_qr_url()` and `generate_qr_base64()`. No GUI or BLE dependencies.
- **`_cmd_add_channel`** (`ble/commands.py`): new BLE command handler that calls
  `mc.commands.set_channel(idx, name, secret)` and triggers a full channel
  re-discovery on success so the GUI immediately reflects the new channel.
- **`＋ Add Channel` submenu button** (`gui/dashboard.py`): added to the Messages
  submenu — present on initial render and preserved through all dynamic rebuilds.
- **QR code sharing**: after adding a new private channel the dialog shows a
  scannable QR code (`meshcore://channel/add?name=…&secret=…`) and a
  copy-to-clipboard button for the hex key.

### CHANGED
- `gui/panels/__init__.py`: `ChannelPanel` added to re-exports.
- `gui/dashboard.py`: `ChannelPanel` imported, instantiated in `render()`,
  updated in `_update_ui()` and opened from the `＋ Add Channel` submenu button.
- `ble/commands.py`: `add_channel` registered in the handler dict.

### RATIONALE
- Channels could previously only be added by flashing or using a separate tool.
  The dialog covers all three user scenarios (hashtag join, private create, private
  join) without requiring any changes to the BLE worker's discovery logic.

### IMPACT
- No existing command handlers modified. No existing panel logic altered.
  Pure addition — all existing functionality unaffected.

---

## [1.15.0] - 2026-03-16

### ADDED
- **BOT panel** (`gui/panels/bot_panel.py`): new dedicated panel in the main menu
  (between RX LOG and BBS) with enable toggle, private mode toggle and interactive
  channel assignment via checkboxes built from the live device channel list.
- **BotConfigStore** (`services/bot_config_store.py`): persistent bot configuration
  per device stored at `~/.meshcore-gui/bot/_<dev_id>_bot.json`.  Saves enabled
  flag, private mode state and selected channel set across restarts.
- **Private mode**: when enabled the bot only replies to pinned contacts.  Guard 1.5
  added to `MeshBot.check_and_reply` — reads live from `BotConfigStore` so changes
  take effect immediately without restart.
- **Private mode constraint**: private mode can only be activated when at least one
  contact is pinned.  The toggle is disabled (greyed out) with an explanation label
  when no pinned contacts exist; auto-disables if all pins are removed.
- **Interactive channel assignment**: BOT panel shows a checkbox per discovered
  channel; selection persisted via `BotConfigStore.set_channels()` on Save.
- **`BOT_DIR`** config constant (`~/.meshcore-gui/bot/`) centralising the storage
  root for bot configuration files.

### CHANGED
- **BOT toggle removed from ActionsPanel**: `actions_panel.py` no longer contains
  the BOT checkbox or `set_bot_enabled` wiring; the panel is now solely for Refresh,
  Advertise and Set device name.
- **`MeshBot`** gains two optional constructor arguments: `config_store`
  (`BotConfigStore`) for live channel/private-mode reads, and `pinned_check`
  (`Callable[[str], bool]`) for pin lookups.  Fully backwards-compatible — both
  default to `None` and existing behaviour is preserved when absent.
- **`MeshBot.check_and_reply`** gains optional `sender_pubkey` kwarg used by Guard 1.5.
- **`_BaseWorker`** now accepts optional `pin_store` kwarg; wires `pinned_check` and
  `config_store` into `MeshBot` at construction time.
- **`create_worker`** forwards optional `pin_store` kwarg to subworkers.
- **`DashboardPage`** receives `BotConfigStore` instance; `ActionsPanel` call no
  longer passes `set_bot_enabled`.

### IMPACT
- `ble/events.py`: both `check_and_reply` call sites now pass `sender_pubkey=`.
- `ble/worker.py`: `_BaseWorker`, `SerialWorker`, `BLEWorker`, `create_worker` updated.
- `gui/dashboard.py`: `BotPanel` registered as panel `'bot'`; menu item `🤖 BOT` added.
- `gui/panels/actions_panel.py`: BOT toggle removed; `ActionsPanel.__init__` signature
  simplified to `(put_command)`.
- `config.py`: `VERSION` bumped to `1.15.0`; `BOT_DIR` constant added.

### RATIONALE
Bot functionality was embedded in the Actions panel and had no persistence.  Extracting
it to a dedicated panel and a config store aligns with the existing modularity of the
codebase (cf. BBS panel / BbsConfigStore) and enables future extension.  Private mode
fulfils the requirement to restrict bot replies to trusted contacts only.

---

> **📈 Performance note — v1.13.1 through v1.13.4**
> Although versions 1.13.1–1.13.4 were released as targeted bugfix releases, the
> cumulative effect of the fixes delivered a significant performance improvement:
>
> - **v1.13.1** — Bot non-response fix eliminated a silent failure path that caused
>   repeated dedup-marked command re-evaluation on every message tick.
> - **v1.13.2** — Map display fixes prevented Leaflet from being initialized on hidden
>   zero-size containers, removing a source of repeated failed bootstrap retries and
>   associated DOM churn.
> - **v1.13.3** — Active panel timer gating reduced the 500 ms dashboard update work to
>   only the currently visible panel, cutting unnecessary UI updates and background
>   redraw load substantially — especially noticeable over VPN or on slower hardware.
> - **v1.13.4** — Room Server event classification fix and sender name resolution removed
>   redundant fallback processing paths and reduced per-tick contact lookup overhead.
>
> Users upgrading from v1.12.x or earlier will notice noticeably faster panel switching,
> lower CPU usage during idle operation, and more stable map rendering.

---
## [1.14.3] - 2026-03-16 — BBS !h / !help NameError fix

### Fixed
- 🐛 **`services/bbs_service.py`** — `!h` en `!help` DM-commando's gooiden een `NameError: name 'cu' is not defined` in `_abbrev_table()`.
  - **Root cause**: `cu` werd gedefinieerd in een inner list comprehension `[cu.upper() for cu in categories]`, maar Python 3 list comprehensions hebben een eigen scope. De `if cu.upper() in inv` in de buitenste generator expression kon `cu` daardoor niet bereiken.
  - **Fix**: list comprehension extracted naar een aparte variabele `cats_upper`; de generator itereert nu over die lijst.

## [1.14.2] - 2026-03-16 — BBS whitelist fix: !bbs channel hook in on_rx_log

### Fixed
- 🐛 **`ble/events.py`** — `!bbs` op een geconfigureerd BBS-channel deed nooit een whitelist-add, waardoor `!h` en andere DM-BBS-commando's daarna silently werden gedropped.
  - **Root cause**: de BBS channel hook stond uitsluitend in `on_channel_msg`, maar `on_channel_msg` wordt in het normale pad onderdrukt door de content-dedup early-return (het bericht is dan al door `on_rx_log` verwerkt en gemarkeerd).
  - **Fix**: BBS channel hook (`handle_channel_msg`) ook aangeroepen in `on_rx_log`, direct ná de bot-aanroep, binnen de `GroupText + channel_idx resolved`-branch. `sender_pubkey` is daar al opgelost via `get_contact_by_name`.
  - De hook in `on_channel_msg` blijft intact als fallback voor het deferred-path (channel_idx onopgelost in `on_rx_log`).

## [1.14.1] - 2026-03-16 — BBS test corrections

### Changed
- Testing package flattened to a single canonical `meshcore_gui/...` tree so runtime and validation target one code path.
- `!bbs` channel bootstrap, DM-only `!h` / `!help`, and chunked BBS reply work were applied as in-progress fixes under version `1.14.1` while testing continues.
- No release bump: version numbering is kept at `1.14.1` for this test set.

## [1.14.0] - 2026-03-14 — BBS (Bulletin Board System)

### Added

- 🆕 **BBS — Bulletin Board System** — offline berichtenbord voor mesh-netwerken.
  - **Toegangsmodel:** de beheerder selecteert één of meer channels in de settings. Iedereen die op een van die channels een bericht stuurt, wordt automatisch gewhitelist en kan daarna commando's sturen via **Direct Message** aan de node. Het channel blijft schoon; alleen de eerste interactie verloopt via het channel.
  - Korte syntax: `!p <cat> <tekst>` (post) en `!r [cat]` (lezen). Categorie-afkortingen automatisch berekend als kortste unieke prefix (bijv. `U=URGENT M=MEDICAL`).
  - Volledige syntax behouden: `!bbs post`, `!bbs read`, `!bbs help`.
  - Optioneel regio-filter en handmatige allowed-keys override in Advanced.
  - Settings-pagina (`/bbs-settings`): checkboxes per channel, categorieën, retentie, Advanced voor regio's en handmatige keys.
  - Berichten opgeslagen in SQLite (`~/.meshcore-gui/bbs/bbs_messages.db`, WAL-mode).

### Changed

- 🔄 **`ble/events.py`** — `on_channel_msg` roept `BbsCommandHandler.handle_channel_msg()` aan op geconfigureerde BBS-channels: auto-whitelist + bootstrap reply. `on_contact_msg` stuurt `!`-DMs direct naar `handle_dm()`. Beide paden volledig los van `MeshBot`.
- 🔄 **`services/bot.py`** — `MeshBot` is weer een pure keyword/channel responder; BBS-routing verwijderd.
- 🔄 **`services/bbs_config_store.py`** — `configure_board()` (multi-channel), `add_allowed_key()` (auto-whitelist), `clear_board()`.
- 🔄 **`gui/dashboard.py`** — `BbsPanel` geregistreerd, `📋 BBS` drawer-item toegevoegd.

### Storage
```
~/.meshcore-gui/bbs/bbs_config.json   — board configuratie
~/.meshcore-gui/bbs/bbs_messages.db   — SQLite berichtenopslag
```

---

## [1.13.5] - 2026-03-14 — Route back-button and map popup flicker fixes

### Fixed
- 🛠 **Route page back-button navigated to main menu regardless of origin** — the two fixed navigation buttons (`/` and `/archive`) are replaced by a single `arrow_back` button that calls `window.history.back()`, so the user is always returned to the screen that opened the route page.
- 🛠 **Map marker popup flickered on every 500 ms update tick** — the periodic `applyContacts` / `applyDevice` calls in `leaflet_map_panel.js` invoked `setIcon()` and `setPopupContent()` on all existing markers unconditionally. `setIcon()` rebuilds the marker DOM element; when a popup was open this caused the popup anchor to detach and reattach, producing visible flickering. Both functions now check `marker.isPopupOpen()` and skip icon/content updates while the popup is visible.
- 🛠 **Map marker popup appeared with a flicker/flash on first click (main map and route map)** — Leaflet's default `fadeAnimation: true` caused popups to fade in from opacity 0, which on the Raspberry Pi rendered as a visible flicker. Both `L.map()` initialisations (`ensureMap` and `MeshCoreRouteMapBoot`) now set `fadeAnimation: false` and `markerZoomAnimation: false` so popups appear immediately without animation artefacts.

### Changed
- 🔄 `meshcore_gui/gui/route_page.py` — Replaced two fixed-destination header buttons with a single `arrow_back` button using `window.history.back()`.
- 🔄 `meshcore_gui/static/leaflet_map_panel.js` — `applyDevice` and `applyContacts` guard `setIcon` / `setPopupContent` behind `isPopupOpen()`. Both `L.map()` calls add `fadeAnimation: false, markerZoomAnimation: false`.
- 🔄 `meshcore_gui/config.py` — Version bumped to `1.13.5`.

### Impact
- Back navigation from the route page now always returns to the correct origin screen.
- Open marker popups are stable during map update ticks; content refreshes on next tick after the popup is closed.
- Popup opening is instant on both maps; no animation artefacts on low-power hardware.

---
## [1.13.4] - 2026-03-12 — Room Server message classification fix

### Fixed
- 🛠 **Incoming room messages from other participants could be misclassified as normal DMs** — `CONTACT_MSG_RECV` room detection now keys on `txt_type == 2` instead of requiring `signature`.
- 🛠 **Incoming room traffic could be attached to the wrong key** — room message handling now prefers `room_pubkey` / receiver-style payload keys before falling back to `pubkey_prefix`.
- 🛠 **Room login UI could stay out of sync with the actual server-confirmed state** — `LOGIN_SUCCESS` now updates `room_login_states` and refreshes room history using the resolved room key.
- 🛠 **Room Server panel showed hex codes instead of sender names** — when a contact was not yet known at the time a room message was archived, `msg.sender` was stored as a raw hex prefix. The panel now performs a live lookup against the current contacts snapshot on every render tick, so names are shown as soon as the contact is known.

### Changed
- 🔄 `meshcore_gui/ble/events.py` — Broadened room payload parsing and added payload-key debug logging for incoming room traffic.
- 🔄 `meshcore_gui/ble/worker.py` — `LOGIN_SUCCESS` handler now updates per-room login state and refreshes cached room history.
- 🔄 `meshcore_gui/config.py` — Version kept at `1.13.4`.

### Impact
- Keeps the existing Room Server panel logic intact.
- Fix is limited to room event classification and room login confirmation handling.
- No intended behavioural change for ordinary DMs or channel messages.

---
---
## [1.13.3] - 2026-03-12 — Active Panel Timer Gating

### Changed
- 🔄 `meshcore_gui/gui/dashboard.py` — The 500 ms dashboard timer now keeps only lightweight global state updates running continuously (status label, channel filters/options, drawer submenu consistency). Expensive panel refreshes are now gated to the currently active panel only
- 🔄 `meshcore_gui/gui/dashboard.py` — Added immediate active-panel refresh on panel switch so newly opened panels populate at once instead of waiting for the next timer tick
- 🔄 `meshcore_gui/gui/panels/map_panel.py` — Removed eager hidden `ensure_map` bootstrap from `render()`; the browser map now starts only when real snapshot work exists or when a live map already exists
- 🔄 `meshcore_gui/static/leaflet_map_panel.js` — Theme-only calls without snapshot work no longer start hidden host retry processing before a real map exists
- 🔄 `meshcore_gui/config.py` — Version bumped to `1.13.3`

### Fixed
- 🛠 **Hidden panels still refreshed every 500 ms** — Device, actions, contacts, messages, rooms and RX log are no longer needlessly updated while another panel is active
- 🛠 **Map bootstrap activity while panel is not visible** — Removed one source of `MeshCoreLeafletBoot timeout waiting for visible map host` caused by eager hidden startup traffic
- 🛠 **Slow navigation over VPN** — Reduced unnecessary dashboard-side UI churn by limiting timer-driven work to the active panel

### Impact
- Faster panel switching because the selected panel gets one direct refresh immediately
- Lower background UI/update load on dashboard level, especially when the map panel is not active
- Smaller chance of Leaflet hidden-host retries and related console noise outside active map usage
- No intended functional regression for route maps or visible panel behaviour

---
## [1.13.2] - 2026-03-11 — Map Display Bugfix

### Fixed
- 🛠 **MAP panel blank when contacts list is empty at startup** — dashboard update loop
  had two separate conditional map-update blocks that both silently stopped firing after
  tick 1 when `data['contacts']` was empty. Map panel received no further snapshots and
  remained blank indefinitely.
- 🛠 **Leaflet map initialized on hidden (zero-size) container** — `processPending` in
  the browser runtime called `L.map()` on the host element while it was still
  `display:none` (Vue v-show, panel not yet visible). This produced a broken 0×0 map
  that never recovered because `ensureMap` returned the cached broken state on all
  subsequent calls. Fixed by adding a `clientWidth/clientHeight` guard in `ensureMap`:
  initialization is deferred until the host has real dimensions.
- 🛠 **Route map container had no height** — `route_page.py` used the Tailwind class
  `h-96` for the Leaflet host `<div>`. NiceGUI/Quasar does not include Tailwind CSS,
  so `h-96` had no effect and the container rendered at height 0. Leaflet initialized
  on a zero-height element and produced a blank map.
- 🛠 **Route map not rendered when no node has GPS coordinates** — `_render_map`
  returned early before creating the Leaflet container when `payload['nodes']` was
  empty. Fixed: container is always created; a notice label is shown instead.

### Changed
- 🔄 `meshcore_gui/static/leaflet_map_panel.js` — Added size guard in `ensureMap`:
  returns `null` when host has `clientWidth === 0 && clientHeight === 0` and no map
  state exists yet. `processPending` retries on the next tick once the panel is visible.
- 🔄 `meshcore_gui/gui/dashboard.py` — Consolidated two conditional map-update blocks
  into a single unconditional update while the MAP panel is active. Added `h-96` to the
  DOMCA CSS height overrides for consistency with the route page map container.
- 🔄 `meshcore_gui/gui/route_page.py` — Replaced `h-96` Tailwind class on the route
  map host `<div>` with an explicit inline `style` (height: 24rem). Removed early
  `return` guard so the Leaflet container is always created.

### Impact
- MAP panel now renders reliably on first open regardless of contact/GPS availability
- Route map now always shows with correct height even when route nodes have no GPS
- No breaking changes outside the three files listed above

---
## [1.13.0] - 2026-03-09 — Leaflet Map Runtime Stabilization

### Added
- ✅ `meshcore_gui/static/leaflet_map_panel.js` — Dedicated browser-side Leaflet runtime responsible for map lifecycle, marker registry, clustering and theme handling independent from NiceGUI redraw cycles
- ✅ `meshcore_gui/static/leaflet_map_panel.css` — Styling for browser-side node markers, cluster icons and map container
- ✅ `meshcore_gui/services/map_snapshot_service.py` — Snapshot service that normalizes device/contact map data into a compact payload for the browser runtime
- ✅ Browser-side map state management for center, zoom and theme
- ✅ Theme persistence across reconnect events via browser storage fallback
- ✅ Browser-side contact clustering via `Leaflet.markercluster`
- ✅ Separate non-clustered device marker layer so the own device remains individually visible

### Changed
- 🔄 `meshcore_gui/gui/panels/map_panel.py` — Replaced NiceGUI Leaflet wrapper usage with a pure browser-managed Leaflet container while preserving the existing card layout, theme toggle and center-on-device control
- 🔄 Leaflet bootstrap moved out of inline Python into a dedicated browser runtime loaded from `/static`
- 🔄 Asset loading order is now explicit: Leaflet first, then `Leaflet.markercluster`, then the MeshCore panel runtime
- 🔄 Map initialization now occurs only once per container; NiceGUI refresh cycles no longer recreate the map
- 🔄 Dashboard update loop now sends compact map snapshots instead of triggering redraws
- 🔄 Snapshot processing in the browser is coalesced so only the newest payload is applied
- 🔄 Map markers are managed in separate device/contact layers and updated incrementally by stable node id
- 🔄 Contact markers are rendered inside a persistent cluster layer while the device marker remains outside clustering
- 🔄 Theme switching moved to a dedicated theme channel instead of being embedded in snapshot data

### Fixed
- 🛠 **Map disappearing during dashboard refresh cycles** — prevented repeated map reinitialization caused by the 500 ms NiceGUI update loop
- 🛠 **Markers disappearing between refreshes** — marker updates are now incremental and keyed by node id
- 🛠 **Blank map container on load** — browser bootstrap now waits for DOM host, Leaflet runtime and panel runtime before initialization
- 🛠 **Leaflet clustering bootstrap failure (`L is not defined`)** — resolved by enforcing correct script dependency order before the panel runtime starts
- 🛠 **MarkerClusterGroup failure (`Map has no maxZoom specified`)** — the map now defines `maxZoom` during initial creation before the cluster layer is attached
- 🛠 **Half-initialized map retry cascade (`Map container is already initialized`)** — map state is now registered safely during initialization so a failed attempt cannot trigger a second `L.map(...)` on the same container
- 🛠 **Race condition between queued snapshot and theme selection** — explicit theme changes can no longer be overwritten by stale snapshot payloads
- 🛠 **Viewport jumping back to default center/zoom** — stored viewport is no longer reapplied on each snapshot update
- 🛠 **Theme reverting to default during reconnect** — effective map theme is restored before snapshot processing resumes

### Impact
- Leaflet map is now managed entirely in the browser and is no longer recreated on each dashboard refresh
- Node markers remain stable and no longer flicker or disappear during the 500 ms update cycle
- Dense contact sets can now be rendered with clustering without violating the browser-owned map lifecycle
- Theme switching and viewport state persist reliably across reconnect events
- No breaking changes outside the map subsystem
---
## [1.12.1] - 2026-03-08 — Minor change bot
### Changed
- 🔄 `meshcore_gui/services/bot.py`: remove path id's
### Impact
- No breaking changes — all existing functionality preserved serial.

---

## [1.12.0] - 2026-02-26 — MeshCore Observer Fase 1

### Added
- ✅ **MeshCore Observer daemon** — New standalone read-only daemon (`meshcore_observer.py`) that reads archive JSON files produced by meshcore_gui and meshcore_bridge, aggregates them, and presents a unified NiceGUI monitoring dashboard on port 9093.
- ✅ **ArchiveWatcher** — Core component that polls `~/.meshcore-gui/archive/` for `*_messages.json` and `*_rxlog.json` files, tracks mtime changes, and returns only new entries since previous poll. Thread-safe, zero writes, graceful on corrupt JSON.
- ✅ **Observer dashboard panels** — Sources overview, aggregated messages feed (sorted by timestamp), aggregated RX log table, and statistics panel with uptime/counters/per-source breakdown. Full DOMCA theme (dark + light mode).
- ✅ **Source filter** — Dropdown to filter messages and RX log by archive source.
- ✅ **Channel filter** — Dropdown to filter messages by channel name.
- ✅ **ObserverConfig** — YAML-based configuration with `from_yaml()` classmethod, defaults work without config file.
- ✅ **observer_config.yaml** — Documented config template with all options.
- ✅ **install_observer.sh** — systemd installer (`/opt/meshcore-observer/`, `/etc/meshcore/observer_config.yaml`), with `--uninstall` option.
- ✅ **RxLogEntry raw packet fields** — 5 new fields on `RxLogEntry` dataclass: `raw_payload`, `packet_len`, `payload_len`, `route_type`, `packet_type_num` (all with defaults, backward compatible).
- ✅ **EventHandler.on_rx_log() metadata** — Raw payload hex and packet metadata now passed through to RxLogEntry and archived (preparation for Fase 2 LetsMesh uplink).

### Changed
- 🔄 `meshcore_gui/core/models.py`: RxLogEntry +5 fields with defaults (backward compatible).
- 🔄 `meshcore_gui/ble/events.py`: on_rx_log() fills raw_payload and metadata (~10 lines added).
- 🔄 `meshcore_gui/services/message_archive.py`: add_rx_log() serializes the 5 new RxLogEntry fields.
- 🔄 `meshcore_gui/config.py`: Version bumped to `1.12.0`.

### Impact
- **No breaking changes** — All new RxLogEntry fields have defaults; existing archives and code work identically.
- **New daemon** — meshcore_observer is fully standalone; no imports from meshcore_gui (reads only JSON files).

---

### Added
- ✅ **Serial CLI flags** — `--baud=BAUD` and `--serial-cx-dly=SECONDS` for serial configuration at startup.

### Changed
- 🔄 **Connection layer** — Switched from BLE to serial (`MeshCore.create_serial`) with serial reconnect handling.
- 🔄 `config.py`: Added `SERIAL_BAUDRATE`, `SERIAL_CX_DELAY`, `DEFAULT_TIMEOUT`, `MESHCORE_LIB_DEBUG`; removed BLE PIN settings; version bumped to `1.10.0`.
- 🔄 `meshcore_gui.py` / `meshcore_gui/__main__.py`: Updated usage, banners and defaults for serial ports.
- 🔄 Docs: Updated README and core docs for serial usage; BLE documents marked as legacy.

### Impact
- No breaking changes — all existing functionality preserved serial.

---

## [1.9.11] - 2026-02-19 — Message Dedup Hotfix

### Fixed
- 🛠 **Duplicate messages after (re)connect** — `load_recent_from_archive()` appended archived messages on every connect attempt without clearing existing entries; after N failed connects, each message appeared N times. Method is now idempotent: clears the in-memory list before loading.
- 🛠 **Persistent duplicate messages** — Live BLE events for messages already loaded from archive were not suppressed because the `DualDeduplicator` was never seeded with archived content. Added `_seed_dedup_from_messages()` in `BLEWorker` after cache/archive load and after reconnect.
- 🛠 **Last-line-of-defence dedup in SharedData** — `add_message()` now maintains a fingerprint set (`message_hash` or `channel:sender:text`) and silently skips messages whose fingerprint is already tracked. This guards against duplicates regardless of their source.
- 🛠 **Messages panel empty on first click** — `_show_panel()` made the container visible but relied on the next 500 ms timer tick to populate it. Added an immediate `_messages.update()` call so content is rendered the moment the panel becomes visible.

### Changed
- 🔄 `core/shared_data.py`: Added `_message_fingerprints` set and `_message_fingerprint()` static method; `add_message()` checks fingerprint before insert and evicts fingerprints when messages are rotated out; `load_recent_from_archive()` clears messages and fingerprints before loading (idempotent)
- 🔄 `ble/worker.py`: Added `_seed_dedup_from_messages()` helper; called after `_apply_cache()` and after reconnect `_load_data()` to seed `DualDeduplicator` with existing messages
- 🔄 `gui/dashboard.py`: `_show_panel()` now forces an immediate `_messages.update()` when the messages panel is shown, eliminating the stale-content flash
- 🔄 `config.py`: Version bumped to `1.9.11`

### Impact
- Eliminates all duplicate message display scenarios: initial connect, failed retries, reconnect, and BLE event replay
- No breaking changes — all existing functionality preserved
- Fingerprint set is bounded to the same 100-message cap as the message list

---

## [1.9.10] - 2026-02-19 — Map Tooltips & Separate Own-Position Marker

### Added
- ✅ **Map marker tooltips** — All markers on the Leaflet map now show a tooltip on hover with the node name and type icon (📱, 📡, 🏠) from `TYPE_ICONS`
- ✅ **Separate own-position marker** — The device's own position is now tracked as a dedicated `_own_marker`, independent from contact markers. This prevents the own marker from being removed/recreated on every contact update cycle

### Changed
- 🔄 `gui/panels/map_panel.py`: Renamed `_markers` to `_contacts_markers`; added `_own_marker` attribute; own position marker is only updated when `device_updated` flag is set (not every timer tick); contact markers are only rebuilt when `contacts_updated` is set; added `TYPE_ICONS` import for tooltip icons
- 🔄 `gui/dashboard.py`: Added `self._map.update(data)` call in the `device_updated` block so the own-position marker updates when device info changes (e.g. GPS position update)
- 🔄 `config.py`: Version bumped to `1.9.10`

### Impact
- Map centering on own device now works correctly and updates only when position actually changes
- Contact markers are no longer needlessly destroyed and recreated on every UI timer tick — only on actual contact data changes
- Tooltips make it easy to identify nodes on the map without clicking
- No breaking changes — all existing map functionality preserved

### Credits
- Based on [PR #16](https://github.com/pe1hvh/meshcore-gui/pull/16) by [@rich257](https://github.com/rich257)

---

## [1.9.9] - 2026-02-18 — Variable Landing Page & Operator Callsign

### Added
- ✅ **Configurable operator callsign** — New `OPERATOR_CALLSIGN` constant in `config.py` (default: `"PE1HVH"`). Used in the landing page SVG and the drawer footer copyright label. Change this single value to personalize the entire GUI for a different operator
- ✅ **External landing page SVG** — The DOMCA splash screen is now loaded from a standalone file (`static/landing_default.svg`) instead of being hardcoded in `dashboard.py`. New `LANDING_SVG_PATH` constant in `config.py` points to the SVG file. The placeholder `{callsign}` in the SVG is replaced at runtime with `OPERATOR_CALLSIGN`
- ✅ **Landing page customization** — To use a custom landing page: copy `landing_default.svg` (or create your own SVG), use `{callsign}` wherever the operator callsign should appear, and point `LANDING_SVG_PATH` to your file. The default SVG includes an instructive comment block explaining the placeholder mechanism

### Changed
- 🔄 `config.py`: Added `OPERATOR_CALLSIGN` and `LANDING_SVG_PATH` constants in new **OPERATOR / LANDING PAGE** section; version bumped to `1.9.9`
- 🔄 `gui/dashboard.py`: Removed hardcoded `_DOMCA_SVG` string (~70 lines); added `_load_landing_svg()` helper that reads SVG from disk and replaces `{callsign}` placeholder; CSS variable `--pe1hvh` renamed to `--callsign`; drawer footer copyright label now uses `config.OPERATOR_CALLSIGN`

### Added (files)
- ✅ `static/landing_default.svg` — The original DOMCA splash SVG extracted as a standalone file, with `{callsign}` placeholder and `--callsign` CSS variable. Serves as both the default landing page and a reference template for custom SVGs

### Impact
- Out-of-the-box behavior is identical to v1.9.8 (same DOMCA branding, same PE1HVH callsign)
- Operators personalize by changing 1–2 lines in `config.py` — no code modifications needed
- Fallback: if the SVG file is missing, a minimal placeholder text is shown instead of a crash
- No breaking changes — all existing dashboard functionality (panels, menus, timer, theming) unchanged

---

## [1.9.8] - 2026-02-17 — Bugfix: Route Page Sender ID, Type & Location Not Populated

### Fixed
- 🛠 **Sender ID, Type and Location empty in Route Page** — After the v4.1 refactoring to `RouteBuilder`/`RouteNode`, the sender contact lookup relied solely on `SharedData.get_contact_by_prefix()` (live lock-based) and `get_contact_by_name()`. When both failed (e.g. empty `sender_pubkey` from RX_LOG decode, or name mismatch), `route['sender']` remained `None` and the route table fell through to a hardcoded fallback with `type: '-'`, `location: '-'`. The contact data was available in the snapshot `data['contacts']` but was never searched
- 🛠 **Route table fallback row ignored available contact data** — When `route['sender']` was `None`, the `_render_route_table` method used a static fallback row without attempting to find the contact in the data snapshot. Even when the contact was present in `data['contacts']` with valid type and location, these fields showed as `'-'`

### Changed
- 🔄 `services/route_builder.py`: Added two additional fallback strategies in `build()` after the existing SharedData lookups: (3) bidirectional pubkey prefix match against `data['contacts']` snapshot, (4) case-insensitive `adv_name` match against `data['contacts']` snapshot. Added helper methods `_find_contact_by_pubkey()` and `_find_contact_by_adv_name()` for snapshot-based lookups
- 🔄 `gui/route_page.py`: Added defensive fallback in `_render_route_table()` sender section — when `route['sender']` is `None`, attempts to find the contact in the snapshot via `_find_sender_contact()` before falling back to the static `'-'` row. Added `_find_sender_contact()` helper method

### Impact
- Sender ID (hash), Type and Location are now populated correctly in the route table when the contact is known
- Four-layer lookup chain ensures maximum resolution: (1) SharedData pubkey lookup, (2) SharedData name lookup, (3) snapshot pubkey lookup, (4) snapshot name lookup
- Defensive fallback in route_page guarantees data is shown even if RouteBuilder misses it
- No breaking changes — all existing route page behavior, styling and data flows unchanged

---

## [1.9.7] - 2026-02-17 — Layout Fix: Archive Filter Toggle & Route Page Styling

### Changed
- 🔄 `gui/archive_page.py`: Archive filter card now hidden by default; toggle visibility via a `filter_list` icon button placed right-aligned on the same row as the "📚 Archive" title. Header restructured from single label to `ui.row()` with `justify-between` layout
- 🔄 `gui/route_page.py`: Route page now uses DOMCA theme (imported from `dashboard.py`) with dark mode as default, consistent with the main dashboard. Header restyled from `bg-blue-600` to Quasar-themed header with JetBrains Mono font. Content container changed from `w-full max-w-4xl mx-auto` to `domca-panel` class for consistent responsive sizing
- 🔄 `gui/dashboard.py`: Added `domca-header-text` CSS class with `@media (max-width: 599px)` rule to hide header text on narrow viewports; applied to version label and status label
- 🔄 `gui/route_page.py`: Header label also uses `domca-header-text` class for consistent responsive behaviour

### Added
- ✅ **Archive filter toggle** — `filter_list` icon button in archive header row toggles the filter card visibility on click
- ✅ **Route page close button** — `X` (close) icon button added right-aligned in the route page header; calls `window.close()` to close the browser tab
- ✅ **Responsive header** — On viewports < 600px, header text labels are hidden; only icon buttons (menu, dark mode toggle, close) remain visible

### Impact
- Archive page is cleaner by default — filters only shown when needed
- Route page visually consistent with the main dashboard (DOMCA theme, dark mode, responsive panel width)
- Headers degrade gracefully on mobile (< 600px): only icon buttons visible, no text overflow
- No functional changes — all event handlers, callbacks, data bindings, logic and imports are identical to the input

---

## [1.9.6] - 2026-02-17 — Bugfix: Channel Discovery Reliability

### Fixed
- 🛠 **Channels not appearing (especially on mobile)** — Channel discovery aborted too early on slow BLE connections. The `_discover_channels()` probe used a single attempt per channel slot and stopped after just 2 consecutive empty responses. On mobile BLE stacks (WebBluetooth via NiceGUI) where GATT responses are slower, this caused discovery to abort before finding any channels, falling back to only `[0] Public`
- 🛠 **Race condition: channel update flag lost between threads** — `get_snapshot()` and `clear_update_flags()` were two separate calls, each acquiring the lock independently. If the BLE worker set `channels_updated = True` between these two calls, the GUI consumed the flag via `get_snapshot()` but then `clear_update_flags()` reset it — causing the channel submenu and dropdown to never populate
- 🛠 **Channels disappear on browser reconnect** — When a browser tab is closed and reopened, `render()` creates new (empty) NiceGUI containers for the drawer submenus, but did not reset `_last_channel_fingerprint`. The `_update_submenus()` method compared the new fingerprint against the stale one, found them equal, and skipped the rebuild — leaving the new containers permanently empty. Fixed by resetting both `_last_channel_fingerprint` and `_last_rooms_fingerprint` in `render()`

### Changed
- 🔄 `core/shared_data.py`: New atomic method `get_snapshot_and_clear_flags()` that reads the snapshot and resets all update flags in a single lock acquisition. Internally refactored to `_build_snapshot_unlocked()` helper. Existing `get_snapshot()` and `clear_update_flags()` retained for backward compatibility
- 🔄 `ble/worker.py`: `_discover_channels()` — `max_attempts` increased from 1 to 2 per channel slot; inter-attempt `delay` increased from 0.5s to 1.0s; consecutive error threshold raised from 2 to 3; inter-channel pause increased from 0.15s to 0.3s for mobile BLE stack breathing room
- 🔄 `gui/dashboard.py`: `_update_ui()` now uses `get_snapshot_and_clear_flags()` instead of separate `get_snapshot()` + `clear_update_flags()`; `render()` now resets `_last_channel_fingerprint` and `_last_rooms_fingerprint` to `None` so that `_update_submenus()` rebuilds into the freshly created containers; channel-dependent updates (`update_filters`, `update_channel_options`, `_update_submenus`) now run unconditionally when channel data exists — safe because each method has internal idempotency checks
- 🔄 `gui/panels/messages_panel.py`: `update_channel_options()` now includes an equality check on options dict to skip redundant `.update()` calls to the NiceGUI client on every 500ms timer tick

### Impact
- Channel discovery now survives transient BLE timeouts that are common on mobile connections
- Atomic snapshot eliminates the threading race condition that caused channels to silently never appear
- Browser close+reopen no longer loses channels — the single-instance timer race on the shared `DashboardPage` is fully mitigated
- No breaking changes — all existing API methods retained, all other functionality unchanged

---

## [1.9.5] - 2026-02-16 — Layout Fix: RX Log Table Responsive Sizing

### Fixed
- 🛠 **RX Log table did not adapt to panel/card size** — The table used `max-h-48` (a maximum height cap) instead of a responsive fixed height, causing it to remain small regardless of available space. Changed to `h-40` which is overridden by the existing dashboard CSS to `calc(100vh - 20rem)` — the same responsive pattern used by the Messages panel
- 🛠 **RX Log table did not fill card width** — Added `w-full` class to the table element so it stretches to the full width of the parent card
- 🛠 **RX Log card did not fill panel height** — Added `flex-grow` class to the card container so it expands to fill the available panel space

### Changed
- 🔄 `gui/panels/rxlog_panel.py`: Card classes `'w-full'` → `'w-full flex-grow'` (line 45); table classes `'text-xs max-h-48 overflow-y-auto'` → `'w-full text-xs h-40 overflow-y-auto'` (line 65)

### Impact
- RX Log table now fills the panel consistently on both desktop and mobile viewports
- Layout is consistent with other panels (Messages, Contacts) that use the same `h-40` responsive height pattern
- No functional changes — all event handlers, callbacks, data bindings, logica and imports are identical to the input

---

## [1.9.4] - 2026-02-16 — BLE Address Log Prefix & Entry Point Cleanup

### Added
- ✅ **BLE address prefix in log filename** — Log file is now named `<BLE_ADDRESS>_meshcore_gui.log` (e.g. `AA_BB_CC_DD_EE_FF_meshcore_gui.log`) instead of the generic `meshcore_gui.log`. Makes it easy to identify which device produced which log file when running multiple instances
  - New helper `_sanitize_ble_address()` strips `literal:` prefix and replaces colons with underscores
  - New function `configure_log_file(ble_address)` updates `LOG_FILE` at runtime before the logger is initialised
  - Rotated backups follow the same naming pattern automatically

### Removed
- ❌ **`meshcore_gui/meshcore_gui.py`** — Redundant copy of `main()` that was never imported. All three entry points (`meshcore_gui.py` root, `__main__.py`, and `meshcore_gui/meshcore_gui.py`) contained near-identical copies of the same logic, causing changes to be missed (as demonstrated by this fix). `__main__.py` is now the single source of truth; root `meshcore_gui.py` is a thin wrapper that imports from it

### Changed
- 🔄 `config.py`: Added `_sanitize_ble_address()` and `configure_log_file()`; version bumped to `1.9.4`
- 🔄 `__main__.py`: Added `config.configure_log_file(ble_address)` call before any debug output
- 🔄 `meshcore_gui.py` (root): Reduced to 4-line wrapper importing `main` from `__main__`

### Impact
- Log files are now identifiable per BLE device
- Single source of truth for `main()` eliminates future sync issues between entry points
- Both startup methods (`python meshcore_gui.py` and `python -m meshcore_gui`) remain functional
- No breaking changes — defaults and all existing behaviour unchanged
---

## [1.9.3] - 2026-02-16 — Bugfix: Map Default Location & Payload Type Decoding

### Fixed
- 🛠 **Map centred on hardcoded Zwolle instead of device location** — All Leaflet maps used magic-number coordinates `(52.5, 6.0)` as initial centre and fallback. These are now replaced by a single configurable constant `DEFAULT_MAP_CENTER` in `config.py`. Once the device reports a valid `adv_lat`/`adv_lon`, maps re-centre on the actual device position (existing behaviour, unchanged)
- 🛠 **Payload type shown as raw integer** — Payload type is now retrieved from the decoded payload and translated to human-readable text using MeshCoreDecoder functions, instead of displaying the raw numeric type value

### Changed
- 🔄 `config.py`: Added `DEFAULT_MAP_CENTER` (default: `(52.5168, 6.0830)`) and `DEFAULT_MAP_ZOOM` (default: `9`) constants in new **MAP DEFAULTS** section. Version bumped to `1.9.2`
- 🔄 `gui/panels/map_panel.py`: Imports `DEFAULT_MAP_CENTER` and `DEFAULT_MAP_ZOOM` from config; `ui.leaflet(center=...)` uses config constants instead of hardcoded values
- 🔄 `gui/route_page.py`: Imports `DEFAULT_MAP_CENTER` and `DEFAULT_MAP_ZOOM` from config; fallback coordinates (`or 52.5` / `or 6.0`) replaced by `DEFAULT_MAP_CENTER[0]` / `[1]`; zoom uses `DEFAULT_MAP_ZOOM`

### Impact
- Map default location is now a single-point-of-change in `config.py`
- Payload type is displayed as readable text instead of a raw number
- No breaking changes — all existing map behaviour (re-centre on device position, contact markers) unchanged

## [1.9.2] - 2026-02-15 — CLI Parameters & Cleanup

### Added
- ✅ **`--port=PORT` CLI parameter** — Web server port is now configurable at startup (default: `8081`). Allows running multiple instances simultaneously on different ports
- ✅ **`--ble-pin=PIN` CLI parameter** — BLE pairing PIN is now configurable at startup (default: `123456`). Eliminates the need to edit `config.py` for devices with a non-default PIN, and works in systemd service files
- ✅ **Per-device log file** — Debug log file now includes the BLE address in its filename (e.g. `F0_9E_9E_75_A3_01_meshcore_gui.log`), so multiple instances log to separate files

### Fixed
- 🛠 **BLE PIN not applied from CLI** — `ble/worker.py` imported `BLE_PIN` as a constant at module load time (`from config import BLE_PIN`), capturing the default value `"123456"` before CLI parsing could override `config.BLE_PIN`. Changed to runtime access via `config.BLE_PIN` so the `--ble-pin` parameter is correctly passed to the BLE agent

### Removed
- ❌ **Redundant `meshcore_gui/meshcore_gui.py`** — This file was a near-identical copy of both `meshcore_gui.py` (top-level) and `meshcore_gui/__main__.py`, but was never imported or referenced. Removed to eliminate maintenance risk. The two remaining entry points cover all startup methods: `python meshcore_gui.py` and `python -m meshcore_gui`

### Impact
- Multiple instances can run side-by-side with different ports, PINs and log files
- Service deployments no longer require editing `config.py` — all runtime settings via CLI
- No breaking changes — all defaults are unchanged

---

## [1.9.1] - 2026-02-14 — Bugfix: Dual Reconnect Conflict

### Fixed
- 🛠 **Library reconnect interfered with application reconnect** — The meshcore library's internal `auto_reconnect` (visible in logs as `"Attempting reconnection 1/3"`) ran a fast 3-attempt reconnect cycle without bond cleanup. This prevented the application's own `reconnect_loop` (which does `remove_bond()` + backoff) from succeeding, because BlueZ retained a stale bond → `"failed to discover service"`

### Changed
- 🔄 `ble/worker.py`: Set `auto_reconnect=False` in both `MeshCore.create_ble()` call sites (`_connect()` and `_create_fresh_connection()`), so only the application's bond-aware `reconnect_loop` handles reconnection
- 🔄 `ble/worker.py`: Added `"failed to discover"` and `"service discovery"` to disconnect detection keywords for defensive coverage

### Impact
- Eliminates the ~9 second wasted library reconnect cycle after every BLE disconnect
- Application's `reconnect_loop` (with bond cleanup) now runs immediately after disconnect detection
- No breaking changes — the application reconnect logic was already fully functional

---

## [1.9.0] - 2026-02-14 — BLE Connection Stability

### Added
- ✅ **Built-in BLE PIN agent** — New `ble/ble_agent.py` registers a D-Bus agent with BlueZ to handle PIN pairing requests automatically. Eliminates the need for external `bt-agent.service` and `bluez-tools` package
  - Uses `dbus_fast` (already a dependency of `bleak`, no new packages)
  - Supports `RequestPinCode`, `RequestPasskey`, `DisplayPasskey`, `RequestConfirmation`, `AuthorizeService` callbacks
  - Configurable PIN via `BLE_PIN` in `config.py` (default: `123456`)
- ✅ **Automatic bond cleanup** — New `ble/ble_reconnect.py` provides `remove_bond()` function that removes stale BLE bonds via D-Bus, equivalent to `bluetoothctl remove <address>`. Called automatically on startup and before each reconnect attempt
- ✅ **Automatic reconnect after disconnect** — BLEWorker main loop now detects BLE disconnects (via connection error exceptions) and automatically triggers a reconnect sequence: bond removal → linear backoff wait → fresh connection → re-wire handlers → reload device data
  - Configurable via `RECONNECT_MAX_RETRIES` (default: 5) and `RECONNECT_BASE_DELAY` (default: 5.0s)
  - After all retries exhausted: waits 60s then starts a new retry cycle (infinite recovery)
- ✅ **Generic install script** — `install_ble_stable.sh` auto-detects user, project directory, venv path and entry point to generate systemd service and D-Bus policy. Supports `--uninstall` flag

### Changed
- 🔄 **`ble/worker.py`** — `_async_main()` rewritten with three phases: (1) start PIN agent, (2) remove stale bond, (3) connect + main loop with disconnect detection. Reconnect logic re-wires all event handlers and reloads device data after successful reconnection
- 🔄 **`config.py`** — Added `BLE_PIN`, `RECONNECT_MAX_RETRIES`, `RECONNECT_BASE_DELAY` constants

### Removed
- ❌ **`bt-agent.service` dependency** — No longer needed; PIN pairing is handled by the built-in agent
- ❌ **`bluez-tools` system package** — No longer needed
- ❌ **`~/.meshcore-ble-pin` file** — No longer needed
- ❌ **Manual `bluetoothctl remove` before startup** — Handled automatically
- ❌ **`ExecStartPre` in systemd service** — Bond cleanup is internal

### Impact
- Zero external dependencies for BLE pairing on Linux
- Automatic recovery from the T1000e ~2 hour BLE disconnect issue
- No manual intervention needed after BLE connection loss
- Single systemd service (`meshcore-gui.service`) manages everything
- No breaking changes to existing functionality

---

## [1.8.0] - 2026-02-14 — DRY Message Construction & Archive Layout Unification

### Fixed
- 🛠 **Case-sensitive prefix matching** — `get_contact_name_by_prefix()` and `get_contact_by_prefix()` in `shared_data.py` failed to match path hashes (uppercase, e.g. `'B8'`) against contact pubkeys (lowercase, e.g. `'b8a3f2...'`). Added `.lower()` to both sides of the comparison, consistent with `_resolve_path_names()` which already had it
- 🛠 **Route page 404 from archive** — Archive page linked to `/route/{hash}` but route was registered as `/route/{msg_index:int}`, causing a JSON parse error for hex hash strings. Route parameter changed to `str` with 3-strategy lookup (index → memory hash → archive fallback)
- 🛠 **Three entry points out of sync** — `meshcore_gui.py` (root), `meshcore_gui/meshcore_gui.py` (inner) and `meshcore_gui/__main__.py` had diverging route registrations. All three now use identical `/route/{msg_key}` with `str` parameter

### Changed
- 🔄 **`core/models.py` — DRY factory methods and formatting**
  - `Message.now_timestamp()`: static method replacing 7× hardcoded `datetime.now().strftime('%H:%M:%S')` across `events.py` and `commands.py`
  - `Message.incoming()`: classmethod factory for received messages (`direction='in'`, auto-timestamp)
  - `Message.outgoing()`: classmethod factory for sent messages (`sender='Me'`, `direction='out'`, auto-timestamp)
  - `Message.format_line(channel_names)`: single-line display formatting (`"12:34:56 ← [Public] [2h✓] PE1ABC: Hello mesh!"`), replacing duplicate inline formatting in `messages_panel.py` and `archive_page.py`
- 🔄 **`ble/events.py`** — 4× `Message(...)` constructors replaced by `Message.incoming()`; `datetime` import removed
- 🔄 **`ble/commands.py`** — 3× `Message(...)` constructors replaced by `Message.outgoing()`; `datetime` import removed
- 🔄 **`gui/panels/messages_panel.py`** — 15 lines inline formatting replaced by single `msg.format_line(channel_names)` call
- 🔄 **`gui/archive_page.py` — Layout unified with main page**
  - Multi-row card layout replaced by single-line `msg.format_line()` in monospace container (same style as main page)
  - DM added to channel filter dropdown (post-filter on `channel is None`)
  - Message click opens `/route/{message_hash}` in new tab (was: no click handler on archive messages)
  - Removed `_render_message_card()` (98 lines) and `_render_archive_route()` (75 lines)
  - Removed `RouteBuilder` dependency and `TYPE_LABELS` import
  - File reduced from 445 to 267 lines
- 🔄 **`gui/route_page.py`** — `render(msg_index: int)` → `render(msg_key: str)` with 3-strategy message lookup: (1) numeric index from in-memory list, (2) hash match in memory, (3) `archive.get_message_by_hash()` fallback
- 🔄 **`services/message_archive.py`** — New method `get_message_by_hash(hash)` for single-message lookup by packet hash
- 🔄 **`__main__.py` + `meshcore_gui.py` (both)** — Route changed from `/route/{msg_index}` (int) to `/route/{msg_key}` (str)

### Impact
- DRY: timestamp formatting 7→1 definition, message construction 7→2 factories, line formatting 2→1 method
- Archive page visually consistent with main messages panel (single-line, monospace)
- Archive messages now clickable to open route visualization (was: only in-memory messages)
- Case-insensitive prefix matching fixes path name resolution for contacts with uppercase path hashes
- No breaking changes to BLE protocol handling, dedup, bot, or data storage

### Known Limitations
- DM filter in archive uses post-filtering (query without channel filter + filter on `channel is None`); becomes exact when `query_messages()` gets native DM support

### Parked for later
- Multi-path tracking (enrich RxLogEntry with multiple path observations)
- Events correlation improvements (only if proven data loss after `.lower()` fix)

---

## [1.7.0] - 2026-02-13 — Archive Channel Name Persistence

### Added
- ✅ **Channel name stored in archive** — Messages now persist `channel_name` alongside the numeric `channel` index in `<ADDRESS>_messages.json`, so archived messages retain their human-readable channel name even when the device is not connected
  - `Message` dataclass: new field `channel_name: str` (default `""`, backward compatible)
  - `SharedData.add_message()`: automatically resolves `channel_name` from the live channels list when not already set (new helper `_resolve_channel_name()`)
  - `MessageArchive.add_message()`: writes `channel_name` to the JSON dict
- ✅ **Archive channel selector built from archived data** — Channel filter dropdown on `/archive` now populated via `SELECT DISTINCT channel_name` on the archive instead of the live BLE channels list
  - New method `MessageArchive.get_distinct_channel_names()` returns sorted unique channel names from stored messages
  - Selector shows only channels that actually have archived messages
- ✅ **Archive filter on channel name** — `MessageArchive.query_messages()` parameter changed from `channel: Optional[int]` to `channel_name: Optional[str]` (exact match on name string)

### Changed
- 🔄 `core/models.py`: Added `channel_name` field to `Message` dataclass and `from_dict()`
- 🔄 `core/shared_data.py`: `add_message()` resolves channel name; added `_resolve_channel_name()` helper
- 🔄 `services/message_archive.py`: `channel_name` persisted in JSON; `query_messages()` filters by name; new `get_distinct_channel_names()` method
- 🔄 `gui/archive_page.py`: Channel selector built from `archive.get_distinct_channel_names()`; filter state changed from `_channel_filter` (int) to `_channel_name_filter` (str); message cards show `channel_name` directly from archive

### Fixed
- 🛠 **Main page empty after startup** — After a restart the messages panel showed no messages until new live BLE traffic arrived. `SharedData.load_recent_from_archive()` now loads up to 100 recent archived messages during the cache-first startup phase, so historical messages are immediately visible
  - New method `SharedData.load_recent_from_archive(limit)` — reads from `MessageArchive.query_messages()` and populates the in-memory list without re-archiving
  - `BLEWorker._apply_cache()` calls `load_recent_from_archive()` at the end of cache loading

### Impact
- Archived messages now self-contained — channel name visible without live BLE connection
- Main page immediately shows historical messages after startup (no waiting for live BLE traffic)
- Backward compatible — old archive entries without `channel_name` fall back to `"Ch <idx>"`
- No breaking changes to existing functionality

---

## [1.6.0] - 2026-02-13 — Dashboard Layout Consolidation

### Changed
- 🔄 **Messages panel consolidated** — Filter checkboxes (DM + channels) and message input (text field, channel selector, Send button) are now integrated into the Messages panel, replacing the separate Filter and Input panels
  - DM + channel checkboxes displayed centered in the Messages header row, between the "💬 Messages" label and the "📚 Archive" button
  - Message input row (text field, channel selector, Send button) placed below the message list within the same card
  - `messages_panel.py`: Constructor now accepts `put_command` callable; added `update_filters(data)`, `update_channel_options(channels)` methods and `channel_filters`, `last_channels` properties (all logic 1:1 from FilterPanel/InputPanel); `update()` signature unchanged
- 🔄 **Actions panel expanded** — BOT toggle checkbox moved from Filter panel to Actions panel, below the Refresh/Advert buttons
  - `actions_panel.py`: Constructor now accepts `set_bot_enabled` callable; added `update(data)` method for BOT state sync; `_on_bot_toggle()` logic 1:1 from FilterPanel
- 🔄 **Dashboard layout simplified** — Centre column reduced from 4 panels (Map → Input → Filter → Messages) to 2 panels (Map → Messages)
  - `dashboard.py`: FilterPanel and InputPanel no longer rendered; all dependencies rerouted to MessagesPanel and ActionsPanel; `_update_ui()` call-sites updated accordingly

### Removed (from layout, files retained)
- ❌ **Filter panel** no longer rendered as separate panel — `filter_panel.py` retained in codebase but not instantiated in dashboard
- ❌ **Input panel** no longer rendered as separate panel — `input_panel.py` retained in codebase but not instantiated in dashboard

### Impact
- Cleaner, more compact dashboard: 2 fewer panels in the centre column
- All functionality preserved — message filtering, send, BOT toggle, archive all work identically
- No breaking changes to BLE, services, core or other panels

---

<!-- ADDED: v1.5.0 feature + bugfix entry -->

## [1.5.0] - 2026-02-11 — Room Server Support, Dynamic Channel Discovery & Contact Management

### Added
- ✅ **Room Server panel** — Dedicated per-room-server message panel in the centre column below Messages. Each Room Server (type=3 contact) gets its own `ui.card()` with login/logout controls and message display
  - Click a Room Server contact to open an add/login dialog with password field
  - After login: messages are displayed in the room card; send messages directly from the room panel
  - Password row + login button automatically replaced by Logout button after successful login
  - Room Server author attribution via `signature` field (txt_type=2) — real message author is resolved from the 4-byte pubkey prefix, not the room server pubkey
  - New panel: `gui/panels/room_server_panel.py` — per-room card management with login state tracking
- ✅ **Room Server password store** — Passwords stored outside the repository in `~/.meshcore-gui/room_passwords/<ADDRESS>.json`
  - New service: `services/room_password_store.py` — JSON-backed persistent password storage per BLE device, analogous to `PinStore`
  - Room panels are restored from stored passwords on app restart
- ✅ **Dynamic channel discovery** — Channels are now auto-discovered from the device at startup via `get_channel()` BLE probing, replacing the hardcoded `CHANNELS_CONFIG`
  - Single-attempt probe per channel slot with early stop after 2 consecutive empty slots
  - Channel name and encryption key extracted in a single pass (combined discovery + key loading)
  - Configurable channel caching via `CHANNEL_CACHE_ENABLED` (default: `False` — always fresh from device)
  - `MAX_CHANNELS` setting (default: 8) controls how many slots are probed
- ✅ **Individual contact deletion** — 🗑️ delete button per unpinned contact in the contacts list, with confirmation dialog
  - New command: `remove_single_contact` in BLE command handler
  - Pinned contacts are protected (no delete button shown)
- ✅ **"Also delete from history" option** — Checkbox in the Clean up confirmation dialog to also remove locally cached contact data

<!-- ADDED: Research document reference -->
- ✅ **Room Server protocol research** — `RoomServer_Companion_App_Onderzoek.md` documents the full companion app message flow (login, push protocol, signature mechanism, auto_message_fetching)

### Changed
- 🔄 `config.py`: Removed `CHANNELS_CONFIG` constant; added `MAX_CHANNELS` (default: 8) and `CHANNEL_CACHE_ENABLED` (default: `False`)
- 🔄 `ble/worker.py`: Replaced hardcoded channel loading with `_discover_channels()` method; added `_try_get_channel_info()` helper; `_apply_cache()` respects `CHANNEL_CACHE_ENABLED` setting; removed `_load_channel_keys()` (integrated into discovery pass)
- 🔄 `ble/commands.py`: Added `login_room`, `send_room_msg` and `remove_single_contact` command handlers
- 🔄 `gui/panels/contacts_panel.py`: Contact click now dispatches by type — type=3 (Room Server) opens room dialog, others open DM dialog; added `on_add_room` callback parameter; added 🗑️ delete button per unpinned contact
- 🔄 `gui/panels/messages_panel.py`: Room Server messages filtered from general message view via `_is_room_message()` with prefix matching; `update()` accepts `room_pubkeys` parameter
- 🔄 `gui/dashboard.py`: Added `RoomServerPanel` in centre column; `_update_ui()` passes `room_pubkeys` to Messages panel; added `_on_add_room_server` callback
- 🔄 `gui/panels/filter_panel.py`: Channel filter checkboxes now built dynamically from discovered channels (no hardcoded references)
- 🔄 `services/bot.py`: Removed stale comment referencing hardcoded channels

### Fixed
- 🛠 **Room Server messages appeared as DM** — Messages from Room Servers (txt_type=2) were displayed in the general Messages panel as direct messages. They are now filtered out and shown exclusively in the Room Server panel
- 🛠 **Historical room messages not shown after login** — Post-login fetch loop was polling `get_msg()` before room server had time to push messages over LoRa RF (10–75s per message). Removed redundant fetch loop; the library's `auto_message_fetching` handles `MESSAGES_WAITING` events correctly and event-driven
- 🛠 **Author attribution incorrect for room messages** — Room server messages showed the room server name as sender instead of the actual message author. Now correctly resolved from the `signature` field (4-byte pubkey prefix) via contact lookup

### Impact
- Room Servers are now first-class citizens in the GUI with dedicated panels
- Channel configuration no longer requires manual editing of `config.py`
- Contact list management is more granular with per-contact deletion
- No breaking changes to existing functionality (messages, DM, map, archive, bot, etc.)

---

## [1.4.0] - 2026-02-09 — SDK Event Race Condition Fix

### Fixed
- 🛠 **BLE startup delay of ~2 minutes eliminated** — The meshcore Python SDK (`commands/base.py`) dispatched device response events before `wait_for_events()` registered its subscription. On busy networks with frequent `RX_LOG_DATA` events, this caused `send_device_query()` and `get_channel()` to fail repeatedly with `no_event_received`, wasting 110+ seconds in timeouts

### Changed
- 📄 `meshcore` SDK `commands/base.py`: Rewritten `send()` method to subscribe to expected events **before** transmitting the BLE command (subscribe-before-send pattern), matching the approach used by the companion apps (meshcore.js, iOS, Android). Submitted upstream as [meshcore_py PR #52](https://github.com/meshcore-dev/meshcore_py/pull/52)

### Impact
- Startup time reduced from ~2+ minutes to ~10 seconds on busy networks
- All BLE commands (`send_device_query`, `get_channel`, `get_bat`, `send_appstart`, etc.) now succeed on first attempt instead of requiring multiple retries
- No changes to meshcore_gui code required — the fix is entirely in the meshcore SDK

### Temporary Installation
Until the fix is merged upstream, install the patched meshcore SDK:
```bash
pip install --force-reinstall git+https://github.com/PE1HVH/meshcore_py.git@fix/event-race-condition
```

---

<!-- ADDED: v1.3.2 bugfix entry -->

## [1.3.2] - 2026-02-09 — Bugfix: Bot Device Name Restoration After Restart

### Fixed
- 🛠 **Bot device name not properly restored after restart/crash** — After a restart or crash with bot mode previously active, the original device name was incorrectly stored as the bot name (e.g. `NL-OV-ZWL-STDSHGN-WKC Bot`) instead of the real device name (e.g. `PE1HVH T1000e`). The original device name is now correctly preserved and restored when bot mode is disabled

### Changed
- 🔄 `commands.py`: `set_bot_name` handler now verifies that the stored original name is not already the bot name before saving
- 🔄 `shared_data.py`: `original_device_name` is only written when it differs from `BOT_DEVICE_NAME` to prevent overwriting with the bot name on restart

---

<!-- ADDED: v1.3.1 bugfix entry -->

## [1.3.1] - 2026-02-09 — Bugfix: Auto-add AttributeError

### Fixed
- 🛠 **Auto-add error on first toggle** — Setting auto-add for the first time raised `AttributeError: 'telemetry_mode_base'`. The `set_manual_add_contacts()` SDK call now handles missing `telemetry_mode_base` attribute gracefully

### Changed
- 🔄 `commands.py`: `set_auto_add` handler wraps `set_manual_add_contacts()` call with attribute check and error handling for missing `telemetry_mode_base`

---

<!-- ADDED: New v1.3.0 entry at top -->

## [1.3.0] - 2026-02-08 — Bot Device Name Management

### Added
- ✅ **Bot device name switching** — When the BOT checkbox is enabled, the device name is automatically changed to a configurable bot name; when disabled, the original name is restored
  - Original device name is saved before renaming so it can be restored on BOT disable
  - Device name written to device via BLE `set_name()` SDK call
  - Graceful handling of BLE failures during name change
- ✅ **`BOT_DEVICE_NAME` constant** in `config.py` — Configurable fixed device name used when bot mode is active (default: `;NL-OV-ZWL-STDSHGN-WKC Bot`)

### Changed
- 🔄 `config.py`: Added `BOT_DEVICE_NAME` constant for bot mode device name
- 🔄 `bot.py`: Removed hardcoded `BOT_NAME` prefix ("Zwolle Bot") from bot reply messages — bot replies no longer include a name prefix
- 🔄 `filter_panel.py`: BOT checkbox toggle now triggers device name save/rename via command queue
- 🔄 `commands.py`: Added `set_bot_name` and `restore_name` command handlers for device name switching
- 🔄 `shared_data.py`: Added `original_device_name` field for storing the pre-bot device name

### Removed
- ❌ `BOT_NAME` constant from `bot.py` — bot reply prefix removed; replies no longer prepend a bot display name

---

## [1.2.0] - 2026-02-08 — Contact Maintenance Feature

### Added
- ✅ **Pin/Unpin contacts** (Iteration A) — Toggle to pin individual contacts, protecting them from bulk deletion
  - Persistent pin state stored in `~/.meshcore-gui/cache/<ADDRESS>_pins.json`
  - Pinned contacts visually marked with yellow background
  - Pinned contacts sorted to top of contact list
  - Pin state survives app restart
  - New service: `services/pin_store.py` — JSON-backed persistent pin storage

- ✅ **Bulk delete unpinned contacts** (Iteration B) — Remove all unpinned contacts from device in one action
  - "🧹 Clean up" button in contacts panel with confirmation dialog
  - Shows count of contacts to be removed vs. pinned contacts kept
  - Progress status updates during removal
  - Automatic device resync after completion
  - New service: `services/contact_cleaner.py` — ContactCleanerService with purge statistics

- ✅ **Auto-add contacts toggle** (Iteration C) — Control whether device automatically adds new contacts from mesh adverts
  - "📥 Auto-add" checkbox in contacts panel (next to Clean up button)
  - Syncs with device via `set_manual_add_contacts()` SDK call
  - Inverted logic handled internally (UI "Auto-add ON" = `set_manual_add_contacts(false)`)
  - Optimistic update with automatic rollback on BLE failure
  - State synchronized from device on each GUI update cycle

### Changed
- 🔄 `contacts_panel.py`: Added pin checkbox per contact, purge button, auto-add toggle, DM dialog (all existing functionality preserved)
- 🔄 `commands.py`: Added `purge_unpinned` and `set_auto_add` command handlers
- 🔄 `shared_data.py`: Added `auto_add_enabled` field with thread-safe getter/setter
- 🔄 `protocols.py`: Added `set_auto_add_enabled` and `is_auto_add_enabled` to Writer and Reader protocols
- 🔄 `dashboard.py`: Passes `PinStore` and `set_auto_add_enabled` callback to ContactsPanel
- 🔄 **UI language**: All Dutch strings in `contacts_panel.py` and `commands.py` translated to English

---

### Fixed
- 🛠 **Route table names and IDs not displayed** — Route tables in both current messages (RoutePage) and archive messages (ArchivePage) now correctly show node names and public key IDs for sender, repeaters and receiver

### Changed
- 🔄 **CHANGELOG.md**: Corrected version numbering to semantic versioning, fixed inaccurate references (archive button location, filter state persistence)
- 🔄 **README.md**: Added Message Archive feature, updated project structure, configuration table and architecture diagram
- 🔄 **MeshCore_GUI_Design.docx**: Added ArchivePage, MessageArchive, Models components; updated project structure, protocols, configuration and version history

---

## [1.1.0] - 2026-02-07 — Archive Viewer Feature


### Added
- ✅ **Archive Viewer Page** (`/archive`) — Full-featured message archive browser
  - Pagination (50 messages per page, configurable)
  - Channel filter dropdown (All + configured channels)
  - Time range filter (24h, 7d, 30d, 90d, All time)
  - Text search (case-insensitive)
  - Filter state stored in instance variables (reset on page reload)
  - Message cards with same styling as main messages panel
  - Clickable messages for route visualization (where available)
  - **💬 Reply functionality** — Expandable reply panel per message
  - **🗺️ Inline route table** — Expandable route display per archive message with sender, repeaters and receiver (names, IDs, node types)
  - *(Note: Reply panels and inline route tables removed in v1.8.0, replaced by click-to-route navigation via message hash)*

<!-- CHANGED: "Filter state persistence (app.storage.user)" replaced with "Filter state stored in 
     instance variables" — the code (archive_page.py:36-40) uses self._current_page etc., 
     not app.storage.user. The comment in the code is misleading. -->

<!-- ADDED: "Inline route table" entry — _render_archive_route() in archive_page.py:333-407 
     was not documented. -->
  
- ✅ **MessageArchive.query_messages()** method
  - Filter by: time range, channel, text search, sender
  - Pagination support (limit, offset)
  - Returns tuple: (messages, total_count)
  - Sorting: Newest first
  
- ✅ **UI Integration**
  - "📚 Archive" button in Messages panel header (opens in new tab)
  - Back to Dashboard button in archive page

<!-- CHANGED: "📚 View Archive button in Actions panel" corrected — the button is in 
     MessagesPanel (messages_panel.py:25), not in ActionsPanel (actions_panel.py). 
     ActionsPanel only contains Refresh and Advert buttons. -->

- ✅ **Reply Panel**
  - Expandable reply per message (💬 Reply button)
  - Pre-filled with @sender mention
  - Channel selector
  - Send button with success notification
  - Auto-close expansion after send

### Changed
- 🔄 `SharedData.get_snapshot()`: Now includes `'archive'` field
- 🔄 `MessagesPanel`: Added archive button in header row
- 🔄 Both entry points (`__main__.py` and `meshcore_gui.py`): Register `/archive` route

<!-- CHANGED: "ActionsPanel: Added archive button" corrected to "MessagesPanel" -->

### Performance
- Query: ~10ms for 10k messages with filters
- Memory: ~10KB per page (50 messages)
- No impact on main UI (separate page)

### Known Limitations
- ~~Route visualization only works for messages in recent buffer (last 100)~~ — Fixed in v1.8.0: archive messages now support click-to-route via `get_message_by_hash()` fallback
- Text search is linear scan (no indexing yet)
- Sender filter exists in API but not in UI yet

---

## [1.0.3] - 2026-02-07 — Critical Bugfix: Archive Overwrite Prevention


### Fixed
- 🛠 **CRITICAL**: Fixed bug where archive was overwritten instead of appended on restart
- 🛠 Archive now preserves existing data when read errors occur
- 🛠 Buffer is retained for retry if existing archive cannot be read

### Changed
- 🔄 `_flush_messages()`: Early return on read error instead of overwriting
- 🔄 `_flush_rxlog()`: Early return on read error instead of overwriting
- 🔄 Better error messages for version mismatch and JSON decode errors

### Details
**Problem:** If the existing archive file had a JSON parse error or version mismatch, 
the flush operation would proceed with `existing_messages = []`, effectively 
overwriting all historical data with only the new buffered messages.

**Solution:** The flush methods now:
1. Try to read existing archive first
2. If read fails (JSON error, version mismatch, IO error), abort the flush
3. Keep buffer intact for next retry
4. Only clear buffer after successful write

**Impact:** No data loss on restart or when archive files have issues.

### Testing
- ✅ Added `test_append_on_restart_not_overwrite()` integration test
- ✅ Verifies data is appended across multiple sessions
- ✅ All existing tests still pass

---

## [1.0.2] - 2026-02-07 — RxLog message_hash Enhancement


### Added
- ✅ `message_hash` field added to `RxLogEntry` model
- ✅ RxLog entries now include message_hash for correlation with messages
- ✅ Archive JSON includes message_hash in rxlog entries

### Changed
- 🔄 `events.py`: Restructured `on_rx_log()` to extract message_hash before creating RxLogEntry
- 🔄 `message_archive.py`: Updated rxlog archiving to include message_hash field
- 🔄 Tests updated to verify message_hash persistence

### Benefits
- **Correlation**: Link RX log entries to their corresponding messages
- **Analysis**: Track which packets resulted in messages
- **Debugging**: Better troubleshooting of packet processing

---

## [1.0.1] - 2026-02-07 — Entry Point Fix


### Fixed
- ✅ `meshcore_gui.py` (root entry point) now passes ble_address to SharedData
- ✅ Archive works correctly regardless of how application is started

### Changed
- 🔄 Both entry points (`meshcore_gui.py` and `meshcore_gui/__main__.py`) updated

---

## [1.0.0] - 2026-02-07 — Message & Metadata Persistence


### Added
- ✅ MessageArchive class for persistent storage
- ✅ Configurable retention periods (MESSAGE_RETENTION_DAYS, RXLOG_RETENTION_DAYS, CONTACT_RETENTION_DAYS)
- ✅ Automatic daily cleanup of old data
- ✅ Batch writes for performance
- ✅ Thread-safe with separate locks
- ✅ Atomic file writes
- ✅ Contact retention in DeviceCache
- ✅ Archive statistics API
- ✅ Comprehensive tests (20+ unit, 8+ integration)
- ✅ Full documentation

### Storage Locations
- `~/.meshcore-gui/archive/<ADDRESS>_messages.json`
- `~/.meshcore-gui/archive/<ADDRESS>_rxlog.json`

### Requirements Completed
- R1: All incoming messages persistent ✅
- R2: All incoming RxLog entries persistent ✅
- R3: Configurable retention ✅
- R4: Automatic cleanup ✅
- R5: Backward compatibility ✅
- R6: Contact retention ✅
- R7: Archive stats API ✅

- Fix3: Leaflet asset injection is now per page render instead of process-global, and browser bootstrap now retries until the host element, Leaflet runtime, and MeshCore panel runtime are all available. This fixes blank map containers caused by missing or late-loaded JS/CSS assets.

- Fix5: Removed per-snapshot map invalidate calls, stopped forcing a default dark theme during map bootstrap, and added client-side interaction/resize guards so zooming stays responsive and the theme no longer jumps back during status-loop updates.


## 2026-03-09 map hotfix v2
- regular map snapshots no longer carry theme state
- explicit theme changes are now handled only via the dedicated theme channel
- initial map render now sends an ensure_map command plus an immediate theme sync
- added no-op ensure_map handling in the Leaflet runtime to avoid accidental fallback behaviour
