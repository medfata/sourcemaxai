# Plan: Resource Tabs on Video Selection Step

Replace flat "all videos" list on `VideoListPage` with YouTube-style tabbed UI: **Videos** | **Playlists** | **Shorts**. User selects across tabs; selecting a playlist expands to its underlying video IDs flowed into the next pipeline step.

---

## Goals

- Group channel resources into 3 tabs that mirror YouTube's own organization.
- Keep long-form videos visible without clutter from Shorts.
- Let user pick a whole playlist; expansion to constituent video IDs happens at selection-save time.
- Zero changes to downstream pipeline contract: pipeline still consumes a flat list of `video_ids`.

## Non-Goals

- No nested playlist UX (no drill-down to individual videos inside a playlist).
- No reordering, no playlist creation, no live count of overlap.
- No backend pipeline rewrite — only ingestion/listing layer changes.

---

## Data Model Changes

### `backend/models.py`

Add `is_short: bool` to `Video`:

```python
class Video(BaseModel):
    id: str
    title: str
    upload_date: str
    duration: int
    view_count: int
    thumbnail: str
    is_short: bool = False
```

Add new models:

```python
class Playlist(BaseModel):
    id: str
    title: str
    video_count: int
    thumbnail: str | None = None

class PlaylistList(BaseModel):
    channel_id: str
    playlists: list[Playlist]

class PlaylistVideos(BaseModel):
    playlist_id: str
    video_ids: list[str]
```

### `frontend/src/types.ts`

Mirror above. Add:

```ts
export interface Video {
  id: string
  title: string
  upload_date: string
  duration: number
  view_count: number
  thumbnail: string
  is_short: boolean
}

export interface Playlist {
  id: string
  title: string
  video_count: number
  thumbnail: string | null
}

export interface PlaylistList {
  channel_id: string
  playlists: Playlist[]
}

export interface PlaylistVideos {
  playlist_id: string
  video_ids: string[]
}
```

---

## Backend Changes

### `backend/pipeline/fetch_videos.py`

1. **Shorts detection.** During `fetch_channel_videos`, mark `is_short = duration > 0 and duration <= 60`. Keep all videos in single `videos.json`; do NOT split files. Tab partitioning happens client-side off `is_short`.

   Edge case: undated/zero-duration entries → `is_short = False` (treat as long-form).

2. **New function `fetch_channel_playlists(channel_url) -> list[dict]`.**
   - Run `yt-dlp --flat-playlist --dump-json` against `<channel_url>/playlists`.
   - Each output line is a playlist entry; collect `id`, `title`, `playlist_count` (or `video_count`), thumbnail.
   - Field name varies by yt-dlp version — try `playlist_count` then `video_count` then `n_entries`.
   - Filter out auto-generated playlists (e.g., "Liked videos", "Watch later") if they leak through (defensive only; channel /playlists tab usually excludes them).

3. **New function `fetch_playlist_video_ids(playlist_id) -> list[str]`.**
   - URL: `https://www.youtube.com/playlist?list=<playlist_id>`.
   - `--flat-playlist --print "%(id)s"` → return list of video IDs.
   - Used at selection-expansion time (not preloaded).

### `backend/storage.py`

Add:

```python
def load_playlists(channel_id: str) -> list[dict] | None: ...
def save_playlists(channel_id: str, playlists: list[dict]) -> None: ...
def load_playlist_video_ids(channel_id: str, playlist_id: str) -> list[str] | None: ...
def save_playlist_video_ids(channel_id: str, playlist_id: str, video_ids: list[str]) -> None: ...
```

Files:
- `data/channels/<cid>/playlists.json` → `{"playlists": [...]}`
- `data/channels/<cid>/playlist_videos/<plid>.json` → `{"video_ids": [...]}`

### `backend/routes/videos.py`

Add 2 endpoints:

```
GET  /api/playlists?channel_id=<cid>           → ApiResponse[PlaylistList]
GET  /api/playlists/videos?channel_id=<cid>&playlist_id=<plid>   → ApiResponse[PlaylistVideos]
```

Both follow the `videos` cache-then-fetch pattern: read JSON cache, if missing call yt-dlp and persist.

### Selection persistence — flat IDs

`/api/videos/select` stays unchanged. Frontend is responsible for expanding selected playlists into video IDs before POSTing the selection. Keeps the pipeline contract simple and avoids backend ambiguity over what "selected" means.

---

## Frontend Changes

### `frontend/src/api.ts`

Add:

```ts
playlists: (channelId: string) =>
  apiGet<PlaylistList>(`/api/playlists?channel_id=${channelId}`),
playlistVideos: (channelId: string, playlistId: string) =>
  apiGet<PlaylistVideos>(`/api/playlists/videos?channel_id=${channelId}&playlist_id=${playlistId}`),
```

### `frontend/src/pages/VideoListPage.tsx`

Refactor into tabbed component. Shape:

```
[ Videos (N) | Playlists (P) | Shorts (S) ]
```

State additions:

```ts
const [tab, setTab] = useState<'videos' | 'playlists' | 'shorts'>('videos')
const [playlists, setPlaylists] = useState<Playlist[]>([])
const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<string>>(new Set())
const [playlistsLoading, setPlaylistsLoading] = useState(false)
```

Derive:
- `longVideos = videos.filter(v => !v.is_short)`
- `shortVideos = videos.filter(v => v.is_short)`

**Tab content:**
- **Videos tab** — current grid, but filtered to `longVideos`. Existing per-video toggle.
- **Shorts tab** — same grid, vertical thumbnail aspect (`aspect-[9/16]`), filtered to `shortVideos`.
- **Playlists tab** — grid of playlist cards: thumbnail, title, "N videos" subtitle, checkbox. Toggle puts/removes `playlist.id` in `selectedPlaylistIds`.

**Lazy load playlists.** On first switch to Playlists tab, fetch `api.playlists(channelId)`. Cache in component state.

**Quick actions** stay at the page level but apply to the **current tab's video set** — except in Playlists tab where actions become `Select all playlists` / `Select none`.

**Selection counter (sticky bottom bar):**

Show three counters: `V videos · S shorts · P playlists`, plus the resolved total `T total selected`.

`T` = `selectedIds.size + (sum of video_count for selected playlists)`. Use playlist `video_count` for the optimistic display; the exact deduped count is computed at expansion time.

**Run pipeline (`onRunPipeline`)**: before navigating, expand playlists.

```ts
async function expandSelection(): Promise<string[]> {
  const expanded = new Set(selectedIds)  // direct video selections
  for (const plId of selectedPlaylistIds) {
    const res = await api.playlistVideos(channel.channel_id, plId)
    for (const vid of res.data?.video_ids ?? []) expanded.add(vid)
  }
  return Array.from(expanded)
}
```

Then `await api.selectVideos(channel_id, expanded)` BEFORE calling `onRunPipeline()`. Show a small "Resolving playlists…" state on the Run button while expansion runs.

**Selection persistence semantics:**
- `selectedIds` (direct video toggles) auto-saves to `/api/videos/select` as today.
- `selectedPlaylistIds` is **frontend-only state**; stored in `localStorage` keyed by `cp_playlists_${channelId}` so a refresh keeps the user's playlist picks.
- On Run: expand and overwrite the saved selection with the union.

### Tab visual treatment

Match iOS-style segmented control already in use by the app's design tokens. Sticky under the page header. Empty states per tab:

- Videos empty → "No long-form videos on this channel."
- Shorts empty → "No Shorts on this channel."
- Playlists empty → "This channel has no public playlists."

---

## Migration / Compat

- Existing `videos.json` files lack `is_short`. On load, derive it on the fly: `is_short = 0 < duration <= 60`. No need to re-fetch.
- Existing `selection.json` files keep working unchanged — they're flat video IDs.

---

## Test Plan

Backend:
- `tests/test_fetch_videos.py` — assert `is_short` is True for duration=45, False for duration=300, False for duration=0.
- `tests/test_fetch_playlists.py` — mock yt-dlp output, assert parsed Playlist shape.
- `tests/test_routes_playlists.py` — `/api/playlists` returns 200 + cached data path; `/api/playlists/videos` returns video IDs.

Frontend (manual):
- Channel with all three resource types: tabs render correct counts, switching is instant.
- Playlist selection persists across page reload.
- Selecting overlapping playlist + direct video → run pipeline → no duplicate `video_ids` in saved selection.
- Run button blocks/spinner while expansion runs.
- Empty-state copy for channels missing one of the categories.

---

## Out-of-Scope / Future

- "View videos in this playlist" drill-down.
- Show overlap between playlists.
- Re-fetch button per tab.
- Server-side selection model that natively understands "playlist references".

---

## File Touch List

- `backend/models.py` — add `is_short`, `Playlist`, `PlaylistList`, `PlaylistVideos`.
- `backend/pipeline/fetch_videos.py` — `is_short` flag, new `fetch_channel_playlists`, new `fetch_playlist_video_ids`.
- `backend/storage.py` — playlist load/save helpers.
- `backend/routes/videos.py` — 2 new endpoints.
- `backend/tests/` — new test files above.
- `frontend/src/types.ts` — type additions.
- `frontend/src/api.ts` — 2 client methods.
- `frontend/src/pages/VideoListPage.tsx` — tabbed refactor (largest change).
