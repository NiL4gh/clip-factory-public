"use client";

import { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Play, Scissors, Sparkles,
  Activity, Zap, CheckCircle2,
  Clock, TrendingUp, Music, Type, Download,
  Film, RefreshCw, Eye, EyeOff, ArrowRight, Settings2, Volume2, StopCircle, Trash2, Tag, Copy, AlertTriangle,
  Wand2, Crop, X, Folder
} from 'lucide-react';
import axios from 'axios';
import { ClipPreview } from '@/components/ClipPreview';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { SaaSStudio } from '@/components/SaaSStudio';
import { CampaignModal } from '@/components/campaigns/CampaignModal';
import { StylePanelModal } from '@/components/StylePanelModal';


/* ------------------------------------------------------------------ */
/*  API / WS base — configurable for Colab via NEXT_PUBLIC_API_URL    */
/* ------------------------------------------------------------------ */
const API_BASE =
  (typeof window !== "undefined" && (window as any).__NEXT_PUBLIC_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000/api";

function wsUrl(): string {
  const base = API_BASE.replace(/\/api\/?$/, "");
  const proto = base.startsWith("https") ? "wss" : "ws";
  return `${proto}://${base.replace(/^https?:\/\//, "")}/api/logs`;
}

// Local-only: no tunnel bypass headers needed

const SESSION_URL_KEY = "cf_last_url";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
interface GalleryItem {
  filename: string;
  url: string;
  size_mb: number;
  created_at: string;
  created_at_ts?: number;
  duration?: number;
  rel_path?: string;
}

interface WordTimestamp {
  word: string;
  start: number;
  end: number;
}

function formatTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatEta(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null || isNaN(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${seconds}s remaining`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s remaining`;
}

/* ------------------------------------------------------------------ */
/*  Main Dashboard                                                     */
/* ------------------------------------------------------------------ */
// Defaults match the "viral" preset so clips look intentional out of the box.
// Fields not exposed in the simplified UI keep these sensible values and are still
// sent to the backend (which supports all of them) — see STYLE_PRESETS below.
const DEFAULT_SETTINGS = {
  face_center: true,
  face_track: true,   // ON by default (owner decision 2026-08-18): follows the speaker horizontally
  magic_hook: false,  // Removed (session 12 Chunk 7). Header hook is the only overlay now.
  remove_silence: true,
  caption_style: "Fire",
  caption_pos: "below",  // below the video box (owner decision 2026-08-18); "bottom" = on-video legacy
  bg_music_genre: "None",
  bg_style: "brand",
  layout_mode: "portrait",
  hook_position: "top",
  hook_display: "3s",
  hook_style: "BlackOnWhiteBox",
  show_outro: false,
  title_style: "Impact",
  template: "viral",
  header_font: "montserrat-black",
  caption_font: "montserrat",
  hook_font: "montserrat",
  header_style: "rounded-chunky",
  rounded_corner_radius: 0,
  force_header_text: "",
};

// Proven style combinations. Picking a preset writes the individual fields below
// (the backend reads those, not `template`); `template` is remembered only so the
// dropdown can show which preset is active. No more silent overwrites — each preset
// states exactly what it changes.
const STYLE_PRESETS: Record<string, { label: string; summary: string; changes: Record<string, string> }> = {
  hormozi: {
    label: "⚡ Hormozi",
    summary: "High-impact yellow & white captions, thick outline, dark pill hook header for 5s.",
    changes: { bg_style: "brand", caption_style: "Hormozi", title_style: "Impact", hook_display: "5s", header_style: "dark-pill" },
  },
  viral: {
    label: "🔥 Viral",
    summary: "Bold Fire captions (yellow-orange), brand background, rounded chunky hook header for the first 5s. Best for talking-head clips.",
    changes: { bg_style: "brand", caption_style: "Fire", title_style: "Impact", hook_display: "5s", header_style: "rounded-chunky" },
  },
  voxdoc: {
    label: "📰 Vox Doc",
    summary: "Documentary green accent captions on dark box backdrop, dark-pill header for 5s.",
    changes: { bg_style: "black", caption_style: "VoxDoc", title_style: "Box", hook_display: "5s", header_style: "dark-pill" },
  },
  luxury: {
    label: "👑 Luxury Gold",
    summary: "Gold captions and header, subtle shadows on deep dark background.",
    changes: { bg_style: "black", caption_style: "LuxuryGold", title_style: "Yellow", hook_display: "5s", header_style: "luxury-gold" },
  },
  clean: {
    label: "✨ Clean",
    summary: "Classic captions on a black background, rounded-chunky stacked header, hook for 5s.",
    changes: { bg_style: "black", caption_style: "Classic", title_style: "Box", hook_display: "5s", header_style: "rounded-chunky" },
  },
  cinematic: {
    label: "🎬 Cinematic",
    summary: "Full-frame blurred background, cinematic captions, rounded-chunky hook for 5s.",
    changes: { bg_style: "blur", caption_style: "CinematicSlate", title_style: "None", hook_display: "5s", header_style: "rounded-chunky" },
  },
};

const FONT_MAP: Record<string, string> = {
  'bebas': 'Bebas Neue',
  'bebas neue': 'Bebas Neue',
  'montserrat': 'Montserrat',
  'montserrat-black': 'Montserrat Black',
  'inter': 'Inter',
  'roboto': 'Roboto',
  'poppins': 'Poppins'
};

/* ------------------------------------------------------------------ */
/*  Style Seeds — curated combinations for per-clip randomisation     */
/* ------------------------------------------------------------------ */
type StyleSeed = {
  id: string;
  label: string;
  badgeColor: string; // Tailwind classes for badge background + text + border
  changes: Record<string, string | number>;
};

const STYLE_SEEDS: StyleSeed[] = [
  {
    id: "hormozi_viral",
    label: "⚡ Hormozi Viral",
    badgeColor: "bg-amber-100 text-amber-800 border-amber-300",
    changes: { bg_style: "brand", caption_style: "Hormozi", title_style: "Impact", hook_display: "5s", header_style: "rounded-chunky", header_font: "montserrat-black", caption_font: "montserrat", hook_font: "montserrat", rounded_corner_radius: 40 },
  },
  {
    id: "dark_pill_hook",
    label: "💊 Dark Pill",
    badgeColor: "bg-slate-900 text-amber-400 border-slate-700",
    changes: { bg_style: "brand", caption_style: "Hormozi", title_style: "Impact", hook_display: "5s", header_style: "dark-pill", header_font: "inter", caption_font: "montserrat", hook_font: "inter", rounded_corner_radius: 40 },
  },
  {
    id: "vox_doc",
    label: "📰 Vox Doc",
    badgeColor: "bg-emerald-100 text-emerald-800 border-emerald-300",
    changes: { bg_style: "black", caption_style: "VoxDoc", title_style: "Box", hook_display: "5s", header_style: "dark-pill", header_font: "montserrat-black", caption_font: "inter", hook_font: "montserrat", rounded_corner_radius: 0 },
  },
  {
    id: "mrbeast_punch",
    label: "💥 Beast Punch",
    badgeColor: "bg-yellow-100 text-yellow-800 border-yellow-300",
    changes: { bg_style: "brand", caption_style: "MrBeast", title_style: "Impact", hook_display: "5s", header_style: "rounded-chunky", header_font: "montserrat-black", caption_font: "montserrat", hook_font: "montserrat", rounded_corner_radius: 40 },
  },
  {
    id: "opus_cyber",
    label: "🤖 Opus Cyber",
    badgeColor: "bg-cyan-900 text-cyan-200 border-cyan-700",
    changes: { bg_style: "black", caption_style: "OpusCyber", title_style: "Orange", hook_display: "5s", header_style: "cyber-pill", header_font: "inter", caption_font: "montserrat", hook_font: "inter", rounded_corner_radius: 60 },
  },
  {
    id: "luxury_gold",
    label: "👑 Luxury Gold",
    badgeColor: "bg-yellow-900 text-yellow-200 border-yellow-700",
    changes: { bg_style: "black", caption_style: "LuxuryGold", title_style: "Yellow", hook_display: "5s", header_style: "luxury-gold", header_font: "inter", caption_font: "poppins", hook_font: "inter", rounded_corner_radius: 40 },
  },
  {
    id: "ali_minimal",
    label: "✨ Ali Minimal",
    badgeColor: "bg-sky-100 text-sky-800 border-sky-200",
    changes: { bg_style: "black", caption_style: "AliAbdaal", title_style: "Box", hook_display: "5s", header_style: "minimal-clean", header_font: "inter", caption_font: "poppins", hook_font: "inter", rounded_corner_radius: 0 },
  },
  {
    id: "chunky_clean",
    label: "🎯 Chunky Clean",
    badgeColor: "bg-slate-100 text-slate-700 border-slate-300",
    changes: { bg_style: "black", caption_style: "Classic", title_style: "Box", hook_display: "5s", header_style: "rounded-chunky", header_font: "montserrat-black", caption_font: "poppins", hook_font: "montserrat", rounded_corner_radius: 0 },
  },
  {
    id: "podcast_pop",
    label: "🎙 Studio Podcast",
    badgeColor: "bg-purple-100 text-purple-700 border-purple-200",
    changes: { bg_style: "gradient", caption_style: "PodcastPop", title_style: "Yellow", hook_display: "5s", header_style: "bold-caps-yellow", header_font: "roboto", caption_font: "roboto", hook_font: "montserrat", rounded_corner_radius: 30 },
  },
  {
    id: "italic_editorial",
    label: "✒ Italic Serif",
    badgeColor: "bg-orange-100 text-orange-700 border-orange-200",
    changes: { bg_style: "brand", caption_style: "Fire", title_style: "Impact", hook_display: "5s", header_style: "italic-serif", header_font: "inter", caption_font: "montserrat", hook_font: "inter", rounded_corner_radius: 40 },
  },
];

/** Shuffle 6 seeds into a no-adjacent-duplicate assignment for `count` clips. */
function assignSeedsToClips(count: number): Record<number, string> {
  const ids = STYLE_SEEDS.map(s => s.id);
  const shuffle = (arr: string[]) => {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };
  // Build pool: repeated shuffles, fixing seam duplicates between cycles
  let pool: string[] = [];
  while (pool.length < count) {
    let next = shuffle(ids);
    if (pool.length > 0 && next[0] === pool[pool.length - 1]) {
      [next[0], next[1]] = [next[1], next[0]];
    }
    pool = pool.concat(next);
  }
  const result: Record<number, string> = {};
  for (let i = 0; i < count; i++) result[i] = pool[i];
  return result;
}

/** One-row-per-API-key field for a provider. The backend still stores
 *  multiple keys comma-joined in a single env var, but the UI never makes
 *  the owner type commas — each key gets its own input, committed on
 *  blur/Enter. Keys never contain commas, so the join is unambiguous. */
function ApiKeysStack({ label, placeholder, value, onChange }: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (joined: string) => void;
}) {
  const rows = value ? value.split(",").map(k => k.trim()).filter(Boolean) : [];
  const [draft, setDraft] = useState("");
  const [visible, setVisible] = useState(false);

  const commitDraft = () => {
    const k = draft.trim();
    if (!k) return;
    onChange([...rows, k].join(","));
    setDraft("");
  };

  const removeRow = (idx: number) => {
    onChange(rows.filter((_, j) => j !== idx).join(","));
  };

  const setRow = (idx: number, v: string) => {
    const next = [...rows];
    next[idx] = v.trim();
    onChange(next.filter(k => k).join(","));
  };

  const inputCls = "flex-1 bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-white text-xs font-mono outline-none focus:border-indigo-500";

  return (
    <div>
      <div className="flex items-center justify-between">
        <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{label}</label>
        <button type="button" onClick={() => setVisible(v => !v)} className="text-[10px] font-bold text-slate-500 hover:text-slate-300 transition-all flex items-center gap-1">
          {visible ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />} {visible ? "Hide" : rows.length ? "Show" : ""}
        </button>
      </div>
      <div className="mt-1.5 space-y-2">
        {rows.map((k, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              type={visible ? "text" : "password"}
              value={k}
              onChange={e => setRow(i, e.target.value)}
              placeholder={placeholder}
              className={inputCls}
            />
            <button type="button" onClick={() => removeRow(i)} className="shrink-0 p-2.5 rounded-xl text-slate-500 hover:text-rose-400 hover:bg-rose-950/30 border border-slate-800 transition-all cursor-pointer" title="Remove this key">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <input
            type={visible ? "text" : "password"}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={commitDraft}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); commitDraft(); } }}
            placeholder={rows.length ? "+ Add another key (rotates on rate limit)..." : placeholder}
            className={inputCls}
          />
          <div className="shrink-0 p-2.5 w-[33px]" />
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionId = useMemo(() => crypto.randomUUID(), []);
  const [backendStatus, setBackendStatus] = useState<'connected' | 'disconnected'>('disconnected');

  useEffect(() => {
    const check = async () => {
      try {
        const res = await axios.get(`${API_BASE}/health`, { 
          timeout: 5000,
        });
        setBackendStatus(res.status === 200 ? 'connected' : 'disconnected');
      } catch (err) {
        setBackendStatus('disconnected');
        bootstrapDoneRef.current = false;
      }
    };
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);

  // Suppress default browser context menu for a clean desktop app experience
  useEffect(() => {
    const handleContextMenu = (e: MouseEvent) => {
      e.preventDefault();
    };
    window.addEventListener("contextmenu", handleContextMenu);
    return () => window.removeEventListener("contextmenu", handleContextMenu);
  }, []);

  // Local batch pipeline: poll /api/queue/state every 5s while on the page.
  // Cheap backend call; safe to spam. Owner can confirm the watcher thread
  // is alive by watching the queue length respond to file drops in incoming/.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await axios.get(`${API_BASE}/queue/state`, { timeout: 2000 });
        if (!cancelled && r?.data) {
          setQueueState(r.data);
          // A batch can be running even though this page didn't start it
          // (started before a refresh, or from another source). Attach the
          // visible progress tracking so no batch ever runs invisibly —
          // beginBatchTracking unions the current queue with any ids we
          // already track, so double-attaching is safe.
          const running = !!(r.data.queue_running || r.data.queue_active_item);
          // A stop the user requested is still draining (worker finishing the
          // current step) — never re-attach during it, or the busy UI pops back
          // and it looks like Stop did nothing.
          if (batchStopRequestedRef.current && !running) {
            batchStopRequestedRef.current = false;
          }
          if (running && !batchStopRequestedRef.current && !batchPollRef.current && !batchAttachInFlightRef.current) {
            batchAttachInFlightRef.current = true;
            beginBatchTracking([], 0).finally(() => {
              batchAttachInFlightRef.current = false;
            });
          }
        }
      } catch (err) {
        // Backend not up yet or session disconnected; keep prior state.
      }
    };
    tick();
    const i = setInterval(tick, 5000);
    return () => { cancelled = true; clearInterval(i); };
  }, []);
  const [status, setStatus] = useState("idle");
  const APP_VERSION = "v2.1.0-FINAL-OPUS";
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<any>(null);
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [activeView, setActiveView] = useState<"workspace" | "gallery" | "whop" | "storage">("workspace");
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [gallerySessionMode, setGallerySessionMode] = useState<"current" | "all">("current");
  const logEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const strategizePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const renderPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bootstrapDoneRef = useRef(false);
  const [progress, setProgress] = useState<{percent: number; message: string; eta?: number | null} | null>(null);
  const [recoveryBanner, setRecoveryBanner] = useState<string | null>(null);
  const [backendJobRunning, setBackendJobRunning] = useState({ is_strategizing: false, is_rendering: false });
  // Local batch pipeline state (added 2026-07-12, session 11): watch folder + queue.
  const [queueState, setQueueState] = useState<{
    queue: Array<{path:string;status:string;filename:string;video_id:string;title?:string;started_at?:number;finished_at?:number;clips_count:number;error?:string}>;
    queue_running: boolean;
    queue_active_item: any | null;
    queue_watch_dir: string;
    clips_by_video: Record<string, number[]>;
  }>({ queue: [], queue_running: false, queue_active_item: null, queue_watch_dir: "", clips_by_video: {} });
  const [watchDirInput, setWatchDirInput] = useState("");

  // Batch visibility (added 2026-08-16): the queue used to process videos
  // silently in the background. Track an active batch so the workspace shows
  // a busy state exactly like single-video runs: live console streams
  // pipeline messages, Extract button flips to busy, Stop button kills the
  // whole batch, and a video N/M counter is visible the entire time.
  const [batchRun, setBatchRun] = useState<{
    total: number;
    done: number;
    failed: number;
    currentId?: string | null;
    currentFile?: string | null;
    currentStatus?: string | null;
  } | null>(null);
  const batchOwnIdsRef = useRef<Set<string>>(new Set());
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const batchAttachInFlightRef = useRef(false);
  // True from the moment the user hits Stop until the worker has fully
  // wound down — blocks the background poller from re-attaching the busy UI.
  const batchStopRequestedRef = useRef(false);

  // Model selectors
  const [llmLabel, setLlmLabel] = useState("👑 TokenRouter: Qwen 3.8 Max (Flagship - Free)");
  const [whisperLabel, setWhisperLabel] = useState("⭐ medium");

  const [styleMode, setStyleMode] = useState<"random" | "fixed">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("styleMode") as "random" | "fixed") || "random";
    }
    return "random";
  });

  const [styleAllowlist, setStyleAllowlist] = useState<Record<string, string[]>>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("styleAllowlist");
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (_) {}
      }
    }
    return {
      header: ["italic-serif", "rounded-chunky", "bold-caps-yellow", "minimal-clean", "dark-pill", "cyber-pill", "luxury-gold"],
      title: ["Impact", "Box", "Yellow", "Neon", "Orange", "Suits", "Meme", "ViralItalic"],
      caption: ["Classic", "Outline", "Minimal", "Minimalist", "Fire", "Hormozi", "MrBeast", "OpusCyber", "VoxDoc", "LuxuryGold", "AliAbdaal", "PodcastPop", "CinematicSlate", "NeonGlow"],
      hook: ["BlackOnWhiteBox", "YellowOnBlackBox", "BoldWhite", "BrightYellow", "Suits", "Meme", "None"]
    };
  });

  const [fixedStyle, setFixedStyle] = useState<Record<string, string>>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("fixedStyle");
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch (_) {}
      }
    }
    return {
      header: "rounded-chunky",
      title: "Impact",
      caption: "Hormozi",
      hook: "BlackOnWhiteBox"
    };
  });

  const [showStylePanel, setShowStylePanel] = useState(false);

  const saveStyleSelection = (newMode: "random" | "fixed", newAllowlist: Record<string, string[]>, newFixed: Record<string, string>) => {
    setStyleMode(newMode);
    setStyleAllowlist(newAllowlist);
    setFixedStyle(newFixed);
    localStorage.setItem("styleMode", newMode);
    localStorage.setItem("styleAllowlist", JSON.stringify(newAllowlist));
    localStorage.setItem("fixedStyle", JSON.stringify(newFixed));
  };

  const [campaignBrief, setCampaignBrief] = useState("");
  const [allowNaturalRecomposition, setAllowNaturalRecomposition] = useState(false);
  const [campaigns, setCampaigns] = useState<{ id: string, name: string, brief: string }[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [activeCampaignId, setActiveCampaignId] = useState("");
  const [activeProfile, setActiveProfile] = useState<any>(null);
  const [showCampaignModal, setShowCampaignModal] = useState(false);
  const [showPurgeModal, setShowPurgeModal] = useState(false);
  // Global auto-apply watermark (generation tab). Persisted on the backend;
  // state here only mirrors it for the settings modal.
  const [showWatermarkModal, setShowWatermarkModal] = useState(false);
  const [watermarkCfg, setWatermarkCfg] = useState<{
    enabled: boolean;
    position: string;
    opacity: number;
    scale: number | null;
    has_image: boolean;
  }>({ enabled: false, position: "bottom-center", opacity: 0.85, scale: null, has_image: false });
  const [watermarkSaving, setWatermarkSaving] = useState(false);
  // Global watermark modal's own file picker (distinct from the per-clip
  // editor's `watermarkFile` declared below for the post-render modal).
  const [wmConfigFile, setWmConfigFile] = useState<File | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ isOpen: boolean; title: string; message: string; onConfirm: () => void }>({
    isOpen: false,
    title: "",
    message: "",
    onConfirm: () => {},
  });

  const showConfirm = (title: string, message: string, onConfirm: () => void) => {
    setConfirmModal({
      isOpen: true,
      title,
      message,
      onConfirm: () => {
        setConfirmModal((prev) => ({ ...prev, isOpen: false }));
        onConfirm();
      },
    });
  };

  const fetchActiveCampaign = async () => {
    try {
      const res = await axios.get(`${API_BASE}/campaigns/active`);
      if (res.data?.active_campaign_id) {
        setActiveCampaignId(res.data.active_campaign_id);
        setSelectedCampaignId(res.data.active_campaign_id);
      }
      if (res.data?.profile) {
        setActiveProfile(res.data.profile);
      }
    } catch {
      // Fallback
    }
  };

  const handleSelectCampaign = async (cid: string) => {
    try {
      const res = await axios.post(`${API_BASE}/campaigns/select`, { campaign_id: cid });
      if (res.data?.active_campaign_id) {
        setActiveCampaignId(res.data.active_campaign_id);
        setSelectedCampaignId(res.data.active_campaign_id);
      }
      if (res.data?.profile) {
        setActiveProfile(res.data.profile);
      }
      addLog(`🎯 Active campaign switched to: ${cid}`);
    } catch {
      addLog(`❌ Failed to switch campaign to: ${cid}`);
    }
  };

  const handleOpenOutputDir = async (videoId?: string, folderPath?: string) => {
    try {
      const res = await axios.post(`${API_BASE}/open_output_dir`, {
        video_id: videoId || undefined,
        folder_path: folderPath || undefined
      });
      addLog(`📂 Opened folder in File Explorer: ${res.data?.path || "output"}`);
    } catch {
      addLog("❌ Failed to open directory in File Explorer");
    }
  };

  const handleExportPackage = async () => {
    try {
      const res = await axios.post(`${API_BASE}/whop/export_package`);
      addLog(`📦 Whop Submission Package (${res.data?.clips_exported || 0} clips) exported & opened in Explorer`);
    } catch (err: any) {
      addLog(`❌ Export failed: ${err.response?.data?.detail || "No rendered clips in gallery"}`);
    }
  };
  const [catalogData, setCatalogData] = useState<{llm_catalog:{label:string}[], whisper_catalog:{label:string}[], bgm_genres:string[]}>({llm_catalog:[], whisper_catalog:[], bgm_genres:[]});
  const [renderSettings, setRenderSettings] = useState<Record<number, typeof DEFAULT_SETTINGS>>({});

  // New UI states
  const [globalSettings, setGlobalSettings] = useState(DEFAULT_SETTINGS);
  const [cardRenderStates, setCardRenderStates] = useState<Record<number, "idle" | "queued" | "rendering" | "done" | "error">>({});
  const [sortBy, setSortBy] = useState<"score" | "energy" | "duration" | "hook">("score");
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [pendingRestoreUrl, setPendingRestoreUrl] = useState("");
  const [selectedForRender, setSelectedForRender] = useState<Record<number, boolean>>({});
  const [editedTitles, setEditedTitles] = useState<Record<number, string>>({});
  const [galleryFilter, setGalleryFilter] = useState<"all" | "today" | "over30" | "under30">("all");
  const [clipSeedIds, setClipSeedIds] = useState<Record<number, string>>({});

  // Chunk D3 — post-render editor modals (trim / watermark / crop).
  // One modal at a time; editorTarget holds the gallery item being edited.
  const [editorOp, setEditorOp] = useState<"trim" | "watermark" | "crop" | null>(null);
  const [editorTarget, setEditorTarget] = useState<GalleryItem | null>(null);
  const [editorLoading, setEditorLoading] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [editorData, setEditorData] = useState<{ out_url?: string; out_filename?: string } | null>(null);
  // Per-op form state.
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [trimSeekBy, setTrimSeekBy] = useState<null | HTMLVideoElement>(null);
  const [watermarkFile, setWatermarkFile] = useState<File | null>(null);
  const [watermarkPosition, setWatermarkPosition] = useState<"top-left" | "top-right" | "bottom-left" | "bottom-right">("bottom-right");
  const [cropRatio, setCropRatio] = useState<"9:16" | "1:1" | "4:5">("9:16");

  // Derive (video_id, filename) from a GalleryItem's rel_path.
  // Server layout is <OUTPUT_DIR>/<video_id>/<filename>.mp4 (or legacy flat <filename>.mp4).
  // The D2 routes accept either; missing video_id is sent as empty string and server tries legacy flat.
  const editorIds = (item: GalleryItem): { video_id: string; filename: string } => {
    const rel = item.rel_path || item.filename;
    const parts = rel.split("/");
    if (parts.length >= 2) return { video_id: parts[parts.length - 2], filename: parts[parts.length - 1] };
    return { video_id: "", filename: item.filename };
  };

  const openEditor = (op: "trim" | "watermark" | "crop", item: GalleryItem) => {
    setEditorOp(op);
    setEditorTarget(item);
    setEditorError(null);
    setEditorData(null);
    setTrimStart(0);
    setTrimEnd(typeof item.duration === "number" && item.duration > 0 ? Math.round(item.duration * 10) / 10 : 0);
    setWatermarkFile(null);
    setWatermarkPosition("bottom-right");
    setCropRatio("9:16");
  };

  const closeEditor = () => {
    setEditorOp(null);
    setEditorTarget(null);
    setEditorLoading(false);
    setEditorError(null);
    setEditorData(null);
    setTrimSeekBy(null);
    setWatermarkFile(null);
  };

  const submitEditor = async () => {
    if (!editorOp || !editorTarget) return;
    const { video_id, filename } = editorIds(editorTarget);
    if (!video_id && !filename) {
      setEditorError("Cannot resolve video_id from gallery item.");
      return;
    }
    setEditorLoading(true);
    setEditorError(null);
    setEditorData(null);
    try {
      // watermark is multipart (PNG upload); trim + crop stay JSON.
      if (editorOp === "watermark") {
        if (!watermarkFile) {
          setEditorError("Pick a PNG file to use as the watermark.");
          setEditorLoading(false);
          return;
        }
        const fd = new FormData();
        fd.append("video_id", video_id);
        fd.append("filename", filename);
        fd.append("position", watermarkPosition);
        fd.append("watermark", watermarkFile, watermarkFile.name || "watermark.png");
        const res = await axios.post(`${API_BASE}/editor/watermark`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setEditorData({ out_url: res.data?.out_url, out_filename: res.data?.out_filename });
        addLog(`✅ Editor watermark: ${res.data?.out_filename || "done"}`);
        setTimeout(() => { fetchGallery(); }, 250);
        return;
      }
      const body: Record<string, unknown> = { video_id, filename };
      if (editorOp === "trim") {
        if (!isFinite(trimStart) || trimStart < 0 || !isFinite(trimEnd) || trimEnd <= 0 || trimEnd <= trimStart) {
          setEditorError("Trim: end_s must be greater than start_s, both ≥ 0.");
          setEditorLoading(false);
          return;
        }
        body.start_s = trimStart;
        body.end_s = trimEnd;
      } else if (editorOp === "crop") {
        body.ratio = cropRatio;
      }
      const res = await axios.post(`${API_BASE}/editor/${editorOp}`, body);
      setEditorData({ out_url: res.data?.out_url, out_filename: res.data?.out_filename });
      addLog(`✅ Editor ${editorOp}: ${res.data?.out_filename || "done"}`);
      // Refresh gallery so the new file shows up next to the original.
      setTimeout(() => { fetchGallery(); }, 250);
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || `${editorOp} failed`;
      setEditorError(typeof msg === "string" ? msg : JSON.stringify(msg));
      addLog(`❌ Editor ${editorOp} failed: ${typeof msg === "string" ? msg : "see modal"}`);
    } finally {
      setEditorLoading(false);
    }
  };

  // ── Global auto-apply watermark (generation tab) ──────────────────────────
  const openWatermarkModal = async () => {
    setWmConfigFile(null);
    try {
      const res = await axios.get(`${API_BASE}/watermark/config`);
      setWatermarkCfg({
        enabled: !!res.data?.enabled,
        position: res.data?.position || "bottom-center",
        opacity: typeof res.data?.opacity === "number" ? res.data.opacity : 0.85,
        scale: res.data?.scale ?? null,
        has_image: !!res.data?.has_image,
      });
    } catch (e) {
      addLog("⚠️ Could not load watermark settings — using defaults.");
    }
    setShowWatermarkModal(true);
  };

  const saveWatermarkConfig = async () => {
    setWatermarkSaving(true);
    try {
      const fd = new FormData();
      fd.append("enabled", String(watermarkCfg.enabled));
      fd.append("position", watermarkCfg.position);
      fd.append("opacity", String(watermarkCfg.opacity));
      if (watermarkCfg.scale != null) fd.append("scale", String(watermarkCfg.scale));
      if (wmConfigFile) fd.append("png", wmConfigFile, wmConfigFile.name || "watermark.png");
      const res = await axios.post(`${API_BASE}/watermark/config`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setWatermarkCfg({
        enabled: !!res.data?.enabled,
        position: res.data?.position || watermarkCfg.position,
        opacity: typeof res.data?.opacity === "number" ? res.data.opacity : watermarkCfg.opacity,
        scale: res.data?.scale ?? null,
        has_image: !!res.data?.has_image,
      });
      setWmConfigFile(null);
      addLog(watermarkCfg.enabled
        ? "✅ Global watermark ON — burned into every clip from now on."
        : "ℹ️ Global watermark OFF.");
      setShowWatermarkModal(false);
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || "failed";
      addLog(`❌ Saving watermark config failed: ${typeof msg === "string" ? msg : "see modal"}`);
    } finally {
      setWatermarkSaving(false);
    }
  };

  const clearWatermark = async () => {
    try {
      await axios.delete(`${API_BASE}/watermark/config`);
      setWatermarkCfg({ enabled: false, position: "bottom-center", opacity: 0.85, scale: null, has_image: false });
      addLog("🗑️ Global watermark removed.");
      setShowWatermarkModal(false);
    } catch (e) {
      addLog("❌ Clearing watermark failed.");
    }
  };

  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"models" | "folders" | "api">("models");
  const [storageInfo, setStorageInfo] = useState<{models: any[], sessions: any[]}>({models: [], sessions: []});
  const [apiKeys, setApiKeys] = useState({TOKENROUTER_API_KEY: "", GEMINI_API_KEY: "", GROQ_API_KEY: "", OPENROUTER_API_KEY: "", GLM_API_KEY: "", NVIDIA_API_KEY: ""});

  useEffect(() => {
    if (showSettings) {
      axios.get(`${API_BASE}/settings`)
        .then(res => {
          if (res.data?.api_keys) {
            setApiKeys(res.data.api_keys);
          }
        })
        .catch(() => {});

      if (settingsTab === "folders") {
        axios.get(`${API_BASE}/storage`).then(res => setStorageInfo(res.data)).catch(() => {});
      }
    }
  }, [showSettings, settingsTab]);

  // Colab tunnel watchdog removed — local-only app does not use tunnels.

  const saveSettings = async () => {
    try {
      await axios.post(`${API_BASE}/settings`, { api_keys: apiKeys });
      alert("Settings saved securely!");
    } catch (e: any) {
      alert("Failed to save settings: " + (e.response?.data?.detail || e.message));
    }
  };

  const deleteModel = async (filename: string) => {
    showConfirm("Delete Model", `Delete model ${filename}?`, async () => {
      try {
        await axios.delete(`${API_BASE}/models/${encodeURIComponent(filename)}`);
        setStorageInfo((prev) => ({ ...prev, models: prev.models.filter((m) => m.filename !== filename) }));
      } catch {}
    });
  };

  const deleteSession = async (video_id: string) => {
    showConfirm("Delete Session", `Delete session ${video_id}?`, async () => {
      try {
        await axios.delete(`${API_BASE}/sessions/${encodeURIComponent(video_id)}`);
        setStorageInfo((prev) => ({ ...prev, sessions: prev.sessions.filter((s) => s.video_id !== video_id) }));
      } catch {}
    });
  };

  const addLog = (message: string) => {
    const timestampRegex = /^\[\d{2}:\d{2}:\d{2}\]/;
    if (timestampRegex.test(message)) {
      setLogs(prev => [...prev, message]);
    } else {
      const now = new Date();
      const hh = now.getHours().toString().padStart(2, '0');
      const mm = now.getMinutes().toString().padStart(2, '0');
      const ss = now.getSeconds().toString().padStart(2, '0');
      setLogs(prev => [...prev, `[${hh}:${mm}:${ss}] ${message}`]);
    }
  };

  const selectedCount = useMemo(() => {
    return Object.values(selectedForRender).filter(Boolean).length;
  }, [selectedForRender]);

  const filteredGallery = useMemo(() => {
    return gallery.filter(video => {
      if (galleryFilter === "all") return true;
      if (galleryFilter === "today") {
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        const midnightTs = midnight.getTime() / 1000;
        return (video as any).created_at_ts >= midnightTs;
      }
      if (galleryFilter === "over30") {
        return ((video as any).duration || 0) >= 30;
      }
      if (galleryFilter === "under30") {
        return ((video as any).duration || 0) < 30;
      }
      return true;
    });
  }, [gallery, galleryFilter]);

  const clearGallery = async () => {
    showConfirm("Clear Gallery", "Are you sure you want to clear all rendered clips from the gallery? This cannot be undone.", async () => {
      try {
        await axios.post(`${API_BASE}/clear_gallery`);
        addLog("🗑️ Gallery cleared.");
        fetchGallery();
      } catch (err: any) {
        const msg = err.response?.data?.detail || err.message || "Unknown error";
        addLog(`❌ Failed to clear gallery: ${msg}`);
      }
    });
  };

  const clearCurrentRenders = async () => {
    showConfirm("Clear Current Renders", "Are you sure you want to clear rendered clips for the CURRENT active video? This cannot be undone.", async () => {
      try {
        await axios.post(`${API_BASE}/clear_gallery?project_only=true`);
        addLog("🗑️ Current video renders cleared.");
        if (results?.clips) {
          const updatedClips = results.clips.map((c: any) => ({ ...c, rendered_filename: undefined }));
          setResults((prev: any) => (prev ? { ...prev, clips: updatedClips } : prev));
        }
        fetchGallery();
      } catch (err: any) {
        const msg = err.response?.data?.detail || err.message || "Unknown error";
        addLog(`❌ Failed to clear current renders: ${msg}`);
      }
    });
  };


  useEffect(() => {
    if (activeView === "gallery") fetchGallery();
  }, [activeView, gallerySessionMode, results?.video_id]);

  useEffect(() => {
    axios.get(`${API_BASE}/heartbeat`)
      .then(res => setBackendVersion(res.data.version))
      .catch(() => setBackendVersion("Offline"));
    axios.get(`${API_BASE}/config`)
      .then(res => {
        setCatalogData(res.data);
        if (res.data?.llm_catalog?.length > 0) {
          setLlmLabel((prev: string) => {
            const exists = res.data.llm_catalog.some((m: any) => m.label === prev);
            return exists ? prev : res.data.llm_catalog[0].label;
          });
        }
      })
      .catch(() => {});
    axios.get(`${API_BASE}/campaigns`)
      .then(res => {
        setCampaigns(res.data.campaigns || []);
      })
      .catch(() => {});
    fetchActiveCampaign();
  }, []);

  useEffect(() => {
    if (selectedCampaignId) {
      const camp = campaigns.find(c => c.id === selectedCampaignId);
      if (camp) {
        setCampaignBrief(camp.brief);
      }
    }
  }, [selectedCampaignId, campaigns]);

  // Auto-populate render settings from persona
  useEffect(() => {
    if (results?.clips?.length && results?.persona) {
      const base = {
        ...globalSettings,
        bg_music_genre: results.persona.suggested_bgm || "None",
      };
      const init: Record<number, typeof DEFAULT_SETTINGS> = {};
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });

      // Auto-assign a distinct seed style to every clip
      const seedAssignment = assignSeedsToClips(results.clips.length);
      results.clips.forEach((_: any, idx: number) => {
        const seed = STYLE_SEEDS.find(s => s.id === seedAssignment[idx]);
        if (seed) init[idx] = { ...init[idx], ...(seed.changes as any) };
      });
      setRenderSettings(init);
      setClipSeedIds(seedAssignment);

      // Pre-select top 5 clips by composite score (clip.score or clip.virality_score)
      const sortedIdxs = results.clips
        .map((c: any, i: number) => ({ idx: i, score: c.virality_score || c.score || 0 }))
        .sort((a: any, b: any) => b.score - a.score)
        .slice(0, 5)
        .map((item: any) => item.idx);
      
      const newSelected: Record<number, boolean> = {};
      results.clips.forEach((_: any, idx: number) => {
        newSelected[idx] = sortedIdxs.includes(idx);
      });
      setSelectedForRender(newSelected);
    }
  }, [results]);

  const fetchGallery = async () => {
    try {
      let query = "";
      if (gallerySessionMode === "current") {
        // Prefer video_id from results state; fall back to /api/results for the
        // current backend session (handles page refresh where results state is lost).
        const vid = results?.video_id;
        if (vid) {
          query = `?video_id=${vid}`;
        } else {
          try {
            const stateRes = await axios.get(`${API_BASE}/results`);
            const backendVid = stateRes.data?.video_id;
            if (backendVid) query = `?video_id=${backendVid}`;
          } catch {
            // Fall through — show all clips as safe fallback
          }
        }
      }
      const res = await axios.get(`${API_BASE}/gallery${query}`);
      setGallery(res.data);
    } catch { /* silently fail */ }
  };

  const getSettings = (clipIdx: number) => renderSettings[clipIdx] || globalSettings;
  const updateSetting = (clipIdx: number, key: string, value: any) => {
    setRenderSettings(prev => ({
      ...prev,
      [clipIdx]: { ...(prev[clipIdx] || globalSettings), [key]: value }
    }));
  };
  const updateGlobalSetting = (key: string, value: any) => {
    setGlobalSettings(prev => {
      const updated = { ...prev, [key]: value };
      if (results?.clips?.length) {
        setRenderSettings(rPrev => {
          const rUpdated = { ...rPrev };
          results.clips.forEach((_: any, idx: number) => {
            rUpdated[idx] = { ...(rUpdated[idx] || updated), [key]: value };
          });
          return rUpdated;
        });
      }
      return updated;
    });
  };
  const handleCancel = async () => {
    // Stop Process during a batch stops the entire queue, not just one video.
    // stopBatchTracking is declared later in this scope but is fully defined
    // by the time a click fires (TDZ only matters pre-initialization).
    if (batchRun) {
      await stopBatchTracking();
      return;
    }
    // Queued-but-not-started videos (nothing runs automatically anymore):
    // "Clear Queued Videos" empties the whole queue so the Start button
    // returns to the normal single-video mode.
    const pendingNow = (queueState?.queue || []).filter((i: any) => i.status === "pending");
    if (pendingNow.length > 0) {
      try {
        await axios.post(`${API_BASE}/queue/clear`);
        const q = await axios.get(`${API_BASE}/queue/state`, { timeout: 3000 });
        setQueueState(q.data);
        addLog(`🗑 Cleared ${pendingNow.length} queued video(s) — nothing will process.`);
      } catch {}
      return;
    }
    try {
      await axios.post(`${API_BASE}/cancel_strategize`);
      setStatus("idle");
      setProgress(null);
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
      addLog("❌ Analysis cancelled by user.");
    } catch {}
  };

  const handlePurge = () => {
    setShowPurgeModal(true);
  };

  const confirmPurge = async () => {
    setShowPurgeModal(false);
    try {
      await axios.post(`${API_BASE}/purge_current`);
      // Reset UI immediately
      setUrl("");
      setStatus("idle");
      setLogs([]);
      setResults(null);
      setSelectedClip(null);
      setProgress(null);
      setCardRenderStates({});
      setSelectedForRender({});
      setEditedTitles({});
      setRecoveryBanner(null);
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      sessionStorage.removeItem(SESSION_URL_KEY);
      bootstrapDoneRef.current = false;
      clearAllConnections();
      addLog("🧹 Session purged and state reset cleanly.");
    } catch (err: any) {
      addLog("❌ Purge failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const handleReset = async () => {
    // Reset UI immediately — don't let a failed backend call leave the UI frozen
    setUrl("");
    setStatus("idle");
    setLogs([]);
    setResults(null);
    setSelectedClip(null);
    setProgress(null);
    setCardRenderStates({});
    setSelectedForRender({});
    setEditedTitles({});
    setRecoveryBanner(null);
    setBackendJobRunning({ is_strategizing: false, is_rendering: false });
    sessionStorage.removeItem(SESSION_URL_KEY);
    bootstrapDoneRef.current = false;
    clearAllConnections();
    // Best-effort backend reset — if the tunnel is down this still won't block
    try { await axios.post(`${API_BASE}/reset`); } catch {}
  };

  const clearAllConnections = () => {
    if (strategizePollRef.current) {
      clearInterval(strategizePollRef.current);
      strategizePollRef.current = null;
    }
    if (renderPollRef.current) {
      clearInterval(renderPollRef.current);
      renderPollRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  const connectWebSocket = () => {
    wsRef.current?.close();
    const ws = new WebSocket(wsUrl());
    ws.onmessage = handleWsMessage;
    ws.onclose = () => {
      // Tunnel WebSocket drops are common during long renders. If this is still
      // the active socket and a job is being tracked, reconnect so the live
      // progress/log stream resumes instead of silently freezing.
      const jobActive = !!(strategizePollRef.current || renderPollRef.current);
      if (wsRef.current === ws && jobActive) {
        setTimeout(() => {
          if (strategizePollRef.current || renderPollRef.current) connectWebSocket();
        }, 1500);
      }
    };
    wsRef.current = ws;
  };

  const persistSessionUrl = (targetUrl: string) => {
    if (targetUrl) sessionStorage.setItem(SESSION_URL_KEY, targetUrl);
  };

  const applyResults = (data: any, banner?: string | null) => {
    setResults(data);
    setStatus("done");
    setBackendJobRunning({ is_strategizing: false, is_rendering: false });
    if (data.current_url) {
      setUrl(data.current_url);
      persistSessionUrl(data.current_url);
    }
    if (banner) setRecoveryBanner(banner);
    // The heavy word-level transcript is no longer in /api/results (it stalled
    // the tunnel on long videos). Fetch it once, on demand, and merge it in so
    // the sentence-exclusion panel keeps working.
    if (data.clips?.length) {
      axios.get(`${API_BASE}/word_timestamps`)
        .then(res => {
          setResults((prev: any) => prev ? { ...prev, word_timestamps: res.data.word_timestamps } : prev);
        })
        .catch(() => { /* sentence-exclusion degrades to empty; not fatal */ });
    }
  };

  const startStrategizePolling = () => {
    if (strategizePollRef.current) clearInterval(strategizePollRef.current);
    let inFlight = false;
    strategizePollRef.current = setInterval(async () => {
      // Skip this tick if the previous poll hasn't returned yet. Without this,
      // a slow response lets requests pile up faster than they complete and
      // stampede the tunnel into a stall.
      if (inFlight) return;
      inFlight = true;
      try {
        const [statusRes, resultsRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
        ]);
        setBackendJobRunning({
          is_strategizing: !!statusRes.data.is_strategizing,
          is_rendering: !!statusRes.data.is_rendering,
        });
        if (resultsRes.data.status === "done") {
          if (strategizePollRef.current) clearInterval(strategizePollRef.current);
          strategizePollRef.current = null;
          wsRef.current?.close();
          wsRef.current = null;
          applyResults(
            resultsRes.data,
            resultsRes.data.clips?.length
              ? `Recovered your session — ${resultsRes.data.clips.length} clips ready`
              : null
          );
        }
      } catch {
        /* poll again */
      } finally {
        inFlight = false;
      }
    }, 2000);
  };

  // ── Batch visibility ────────────────────────────────────────────────────
  // beginBatchTracking is called when a multi-video upload auto-starts the
  // queue (or after a refresh, to reconnect to a running batch). It puts the
  // workspace into the same "busy" look a single-video run gets (status =
  // strategizing, live console connected, busy button), then polls
  // /api/queue/state to surface per-video progress until every item we
  // queued is finished — then reloads results so the merged clips appear
  // exactly like a single run's output.

  const isWorkStatus = (s?: string | null) =>
    s === "pending" || s === "downloading" || s === "transcribing" || s === "strategizing";

  const stopBatchPolling = () => {
    if (batchPollRef.current) {
      clearInterval(batchPollRef.current);
      batchPollRef.current = null;
    }
  };

  const finishBatchTracking = async (summary?: string | null) => {
    stopBatchPolling();
    batchOwnIdsRef.current = new Set();
    setBatchRun(null);
    // Reload merged results once so every batch video's clips show up below.
    try {
      const resultsRes = await axios.get(`${API_BASE}/results`);
      if (resultsRes.data.status === "done") {
        applyResults(resultsRes.data, summary);
      } else {
        setStatus("done");
        setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      }
    } catch {
      setStatus("done");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
    }
    setProgress(null);
    // Close the live log socket (console history stays rendered).
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
  };

  const startBatchPolling = () => {
    if (batchPollRef.current) clearInterval(batchPollRef.current);
    let inFlight = false;
    batchPollRef.current = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const q = await axios.get(`${API_BASE}/queue/state`, { timeout: 3000 });
        setQueueState(q.data);
        const items = (q.data.queue || []);
        const tracked = items.filter((i: any) => batchOwnIdsRef.current.has(i.video_id));
        const doneCount = tracked.filter((i: any) => i.status === "done").length;
        const failedCount = tracked.filter((i: any) => i.status === "failed").length;
        const current = tracked.find((i: any) => isWorkStatus(i.status)) || null;
        const stillWorking = tracked.some((i: any) => isWorkStatus(i.status));
        // Worker considered alive if the loop flag is on OR an item is
        // actively being worked on; if the worker died we must not poll forever.
        const workerAlive = !!q.data.queue_running || !!q.data.queue_active_item;

        setBatchRun({
          total: tracked.length,
          done: doneCount,
          failed: failedCount,
          currentId: current?.video_id || null,
          currentFile: current?.filename || null,
          currentStatus: current?.status || null,
        });
        setBackendJobRunning(prev => ({ ...prev, is_strategizing: true }));

        if ((!stillWorking || !workerAlive) && batchPollRef.current) {
          const summary = failedCount
            ? `Batch finished — ${doneCount} video(s) done, ${failedCount} failed. Clips below.`
            : `Batch complete — ${doneCount} video(s) processed. All clips below.`;
          await finishBatchTracking(summary);
        }
      } catch {
        /* poll again */
      } finally {
        inFlight = false;
      }
    }, 1500);
  };

  const beginBatchTracking = async (savedPaths: string[], fallbackTotal: number) => {
    // Work out the full remaining batch: everything still to go in the queue
    // PLUS whatever was just uploaded. Union with anything already tracked so
    // adding videos mid-batch keeps the count correct.
    let ids = new Set<string>(batchOwnIdsRef.current);
    let trackedTotal = ids.size;
    try {
      const savedSet = new Set(savedPaths);
      const q = await axios.get(`${API_BASE}/queue/state`, { timeout: 3000 });
      (q.data.queue || []).forEach((item: any) => {
        if (savedSet.has(item.path) || isWorkStatus(item.status)) {
          ids.add(item.video_id);
        }
      });
      trackedTotal = ids.size;
    } catch {
      /* fall back to the count the upload call reported */
    }
    const total = trackedTotal || fallbackTotal;
    if (total <= 0) return;
    batchOwnIdsRef.current = ids;
    setBatchRun({ total, done: 0, failed: 0, currentId: null, currentFile: null, currentStatus: null });
    setStatus("strategizing");
    setProgress({ percent: 0, message: `Starting batch — ${total} video(s) queued...` });
    setBackendJobRunning({ is_strategizing: true, is_rendering: false });
    connectWebSocket();
    startBatchPolling();
    addLog(`🎬 Batch started: ${total} video(s) will now be processed one after another — watch the live console.`);
  };

  // Stop the whole batch: kill the queue worker AND abort the in-flight
  // pipeline of the current video, then leave the tracking state. The stop
  // latch stays raised until the drain is visibly over so the 5s poller
  // never re-attaches the busy UI mid-drain (that made Stop feel broken).
  const stopBatchTracking = async () => {
    batchStopRequestedRef.current = true;
    try { await axios.post(`${API_BASE}/queue/stop`); } catch {}
    try { await axios.post(`${API_BASE}/cancel_strategize`); } catch {}
    addLog("⏹ Batch stopped — no further videos will be processed.");
    await finishBatchTracking("Batch stopped. Nothing else will run until you press Start Batch again.");
  };

  // Explicit user start (owner directive 2026-08-16: upload queues, start waits).
  // Idempotent server-side; attach tracking immediately after so the busy
  // state tracks what the user just started, not what a stale poller saw.
  const startBatchFromUI = async () => {
    try {
      let pendingPaths: string[] = [];
      const q = await axios.get(`${API_BASE}/queue/state`, { timeout: 3000 });
      pendingPaths = (q.data.queue || [])
        .filter((i: any) => i.status === "pending")
        .map((i: any) => i.path);
      if (pendingPaths.length === 0) {
        addLog("No videos waiting in the queue — browse for files first.");
        return;
      }
      batchStopRequestedRef.current = false;
      await axios.post(`${API_BASE}/queue/start`, { llm_label: llmLabel });
      addLog(`▶ Starting batch: ${pendingPaths.length} video(s), model: ${llmLabel}`);
      beginBatchTracking(pendingPaths, pendingPaths.length);
    } catch {
      addLog("❌ Could not start the batch. Make sure the app is running.");
    }
  };

  const startRenderPolling = () => {
    if (renderPollRef.current) clearInterval(renderPollRef.current);
    let inFlight = false;
    renderPollRef.current = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const statusRes = await axios.get(`${API_BASE}/status`);
        setBackendJobRunning({
          is_strategizing: !!statusRes.data.is_strategizing,
          is_rendering: !!statusRes.data.is_rendering,
        });
        if (!statusRes.data.is_rendering) {
          if (renderPollRef.current) clearInterval(renderPollRef.current);
          renderPollRef.current = null;
          wsRef.current?.close();
          wsRef.current = null;
          const resultsRes = await axios.get(`${API_BASE}/results`);
          if (resultsRes.data.status === "done") {
            applyResults(resultsRes.data);
          } else {
            setStatus("done");
          }
          setProgress(null);
          fetchGallery();
        }
      } catch {
        /* poll again */
      } finally {
        inFlight = false;
      }
    }, 2000);
  };

  const beginStrategizeTracking = (targetUrl: string, options?: { clearLogs?: boolean; reconnected?: boolean }) => {
    const clearLogs = options?.clearLogs !== false;
    const reconnected = options?.reconnected === true;
    if (clearLogs) {
      setLogs([]);
      addLog("Initializing AI Director Pipeline...");
    } else if (reconnected) {
      addLog("Reconnected to running strategize job after page refresh...");
    }
    setStatus("strategizing");
    setSelectedClip(null);
    if (!reconnected) setProgress(null);
    setShowRestoreModal(false);
    if (targetUrl) {
      setUrl(targetUrl);
      persistSessionUrl(targetUrl);
    }
    setBackendJobRunning({ is_strategizing: true, is_rendering: false });
    connectWebSocket();
    startStrategizePolling();
  };

  const beginRenderTracking = (options?: { clearLogs?: boolean; reconnected?: boolean }) => {
    if (options?.clearLogs) setLogs([]);
    else if (options?.reconnected) addLog("Reconnected to running render job after page refresh...");
    setStatus("rendering");
    setBackendJobRunning(prev => ({ ...prev, is_rendering: true }));
    connectWebSocket();
    startRenderPolling();
  };

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const [statusRes, resultsRes, queueRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
          axios.get(`${API_BASE}/queue/state`),
        ]);
        if (cancelled) return;

        const isStrategizing = !!statusRes.data.is_strategizing;
        const isRendering = !!statusRes.data.is_rendering;
        const currentUrl =
          statusRes.data.current_url ||
          resultsRes.data.current_url ||
          sessionStorage.getItem(SESSION_URL_KEY) ||
          "";
        setBackendJobRunning({ is_strategizing: isStrategizing, is_rendering: isRendering });
        setQueueState(queueRes.data);

        // A batch may still be processing after a refresh — reconnect the
        // visible tracking to it so the user sees progress, not a dead page.
        const qd = queueRes.data;
        if (qd?.queue_running || qd?.queue_active_item) {
          await beginBatchTracking([], 0);
          setRecoveryBanner("Batch still running — reconnected");
          bootstrapDoneRef.current = true;
          return;
        }

        if (isStrategizing) {
          beginStrategizeTracking(currentUrl, { clearLogs: false, reconnected: true });
          setRecoveryBanner("Job still running — reconnected after refresh");
          bootstrapDoneRef.current = true;
          return;
        }

        if (isRendering) {
          if (currentUrl) {
            setUrl(currentUrl);
            persistSessionUrl(currentUrl);
          }
          beginRenderTracking({ clearLogs: false, reconnected: true });
          setRecoveryBanner("Render in progress — reconnected after refresh");
          bootstrapDoneRef.current = true;
          return;
        }

        if (resultsRes.data.status === "done" && resultsRes.data.clips?.length > 0) {
          applyResults(
            resultsRes.data,
            `Recovered your session — ${resultsRes.data.clips.length} clips ready`
          );
          addLog("Session recovered automatically after page refresh.");
          bootstrapDoneRef.current = true;
          return;
        }

        const savedUrl = sessionStorage.getItem(SESSION_URL_KEY);
        if (savedUrl) {
          setUrl(savedUrl);
          try {
            const checkRes = await axios.post(`${API_BASE}/check_session`, { url: savedUrl });
            if (!cancelled && checkRes.data.exists) {
              setPendingRestoreUrl(savedUrl);
              setShowRestoreModal(true);
            }
          } catch {
            /* ignore */
          }
        }
        bootstrapDoneRef.current = true;
      } catch {
        /* backend unreachable — disconnect banner handles it; retry when connected */
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-bootstrap when backend comes back after a tunnel reconnect (502 → connected)
  useEffect(() => {
    if (backendStatus !== "connected" || bootstrapDoneRef.current) return;
    const retry = async () => {
      try {
        const [statusRes, resultsRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
        ]);
        const isStrategizing = !!statusRes.data.is_strategizing;
        const isRendering = !!statusRes.data.is_rendering;
        if (isStrategizing) {
          beginStrategizeTracking(statusRes.data.current_url || url, { clearLogs: false, reconnected: true });
          setRecoveryBanner("Job still running — reconnected after refresh");
        } else if (isRendering) {
          beginRenderTracking({ clearLogs: false, reconnected: true });
          setRecoveryBanner("Render in progress — reconnected after refresh");
        } else if (resultsRes.data.status === "done" && resultsRes.data.clips?.length > 0) {
          applyResults(
            resultsRes.data,
            `Recovered your session — ${resultsRes.data.clips.length} clips ready`
          );
          addLog("Session recovered after backend reconnected.");
        }
        bootstrapDoneRef.current = true;
      } catch {
        /* ignore */
      }
    };
    retry();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendStatus]);

  useEffect(() => () => clearAllConnections(), []);

  // Blocklist regex — reject raw backend noise from the log console
  const LOG_BLOCKLIST = /DEBUG|ffmpeg|whisper|model_load|frame=|bitrate=|speed=|Lsize=|muxing overhead|Stream #|libx26|matroska|ggml|llama_|llm_load|VRAM|size=\s*\d|cublas|metal|cuda|opengl|vulkan/i;

  const handleWsMessage = (event: MessageEvent) => {
    try {
      const entry = JSON.parse(event.data);
      if (entry.type === "progress") {
        setProgress({ percent: entry.percent || 0, message: entry.message || "", eta: entry.eta });
      } else if (entry.type === "error") {
        addLog(`❌ ERROR: ${entry.message}`);
      } else if (entry.type === "render_status") {
        setCardRenderStates(prev => ({ ...prev, [entry.clip_id]: entry.status }));
      } else if (entry.type === "status") {
        if (!LOG_BLOCKLIST.test(entry.message)) {
          addLog(entry.message);
        }
        // Surface "Topic N/M: ..." lines in the progress bar so the user can see extraction progress
        const topicMatch = entry.message?.match(/Topic (\d+)\/(\d+):\s*"?(.+?)"?\s*$/);
        if (topicMatch) {
          setProgress(prev => prev ? { ...prev, message: `Extracting Topic ${topicMatch[1]}/${topicMatch[2]}: ${topicMatch[3]}` } : prev);
        }
      }
    } catch {
      // Legacy fallback — plain string, still filter
      if (!LOG_BLOCKLIST.test(event.data)) {
        addLog(event.data);
      }
    }
  };

  const startStrategize = async (targetUrl: string) => {
    beginStrategizeTracking(targetUrl);
    try {
      await axios.post(`${API_BASE}/strategize`, {
        url: targetUrl,
        llm_label: llmLabel,
        whisper_label: whisperLabel,
        angle: "multi-angle",
        campaign_brief: campaignBrief.trim() || null,
        allow_natural_recomposition: allowNaturalRecomposition,
        session_id: sessionId
      });
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || "Unknown error";
      console.error(error);
      addLog(`❌ Error starting strategize phase: ${msg}`);
      setStatus("error");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
    }
  };

  const restoreSession = async (targetUrl: string) => {
    setShowRestoreModal(false);
    setStatus("loading");
    setLogs([]);
    addLog("Restoring session from Google Drive...");
    
    try {
      const res = await axios.post(`${API_BASE}/restore_session`, { url: targetUrl });
      if (res.data.status === "success") {
        const resultsRes = await axios.get(`${API_BASE}/results`);
        applyResults(resultsRes.data, `Restored from Google Drive — ${resultsRes.data.clips?.length || 0} clips ready`);
        addLog("✅ Session successfully restored from Google Drive.");
      }
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || "Unknown error";
      addLog(`❌ Failed to restore session: ${msg}`);
      setStatus("error");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length === 0) return;

    // Single video → same flow as always: upload, drop path in the URL field.
    if (files.length === 1) {
      const file = files[0];
      setUploading(true);
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await axios.post(`${API_BASE}/upload_video`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setUrl(res.data.path);
      } catch {
        alert("Upload failed. Make sure the app is running.");
      } finally {
        setUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
      return;
    }

    // Multiple videos → upload queues them but does NOT start anything.
    // The user decides when by clicking Start Batch (owner directive 2026-08-16).
    setUploading(true);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      form.append("llm_label", llmLabel);
      const res = await axios.post(`${API_BASE}/upload_videos_batch`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const d = res.data;
      addLog(`📦 Batch upload: ${d.queued} video(s) ready in the queue (${files.length} selected).`);
      const skipped = d.skipped_duplicates?.length || 0;
      if (skipped) addLog(`⏭️ Skipped ${skipped} duplicate(s) already in the queue.`);
      (d.failed || []).forEach((f: string) => addLog(`❌ Upload failed: ${f}`));
      if (d.queued > 0 || d.queue_length > 0) {
        // Force the queue-state poller's next pass to see fresh counts so the
        // Start Batch button label updates immediately instead of waiting 5s.
        try {
          const q = await axios.get(`${API_BASE}/queue/state`, { timeout: 3000 });
          setQueueState(q.data);
        } catch { /* next 5s poll will catch up */ }
        addLog(`🕐 Nothing is running yet — press "Start Batch (${d.queue_length || d.queued})" when you're ready. The selected model and settings apply at start.`);
      }
    } catch {
      alert("Batch upload failed. Make sure the app is running.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleStrategize = async () => {
    if (!url) return;
    try {
      const statusRes = await axios.get(`${API_BASE}/status`);
      if (statusRes.data.is_strategizing || statusRes.data.is_rendering) {
        addLog("A task is already running on the backend — reconnecting...");
        if (statusRes.data.is_strategizing) {
          beginStrategizeTracking(statusRes.data.current_url || url.trim(), {
            clearLogs: false,
            reconnected: true,
          });
        } else {
          beginRenderTracking({ clearLogs: false, reconnected: true });
        }
        return;
      }
    } catch {
      /* proceed */
    }
    try {
      const checkRes = await axios.post(`${API_BASE}/check_session`, { url: url.trim() });
      if (checkRes.data.exists) {
        setPendingRestoreUrl(url);
        setShowRestoreModal(true);
        return;
      }
    } catch (err) {
      // Ignore and proceed
    }
    await startStrategize(url);
  };

  const renderClip = async (index: number) => {
    beginRenderTracking({ clearLogs: true });

    try {
      const settings = getSettings(index);
      const exSentences = (excludedSentences[index] || []).map(s => `[WID:${s.start_idx}-${s.end_idx}] ${s.text}`);

      const res = await axios.post(`${API_BASE}/render`, {
        clip_id: index,
        ...settings,
        layout_mode: globalSettings.layout_mode || "portrait",
        face_track: (globalSettings.face_track ?? true),
        excluded_sentences: exSentences,
        title: editedTitles[index] || undefined,
        session_id: sessionId,
        style_mode: styleMode,
        style_allowlist: styleAllowlist,
        fixed_style: fixedStyle
      });

      const taskId = res.data.task_id;
      if (renderPollRef.current) clearInterval(renderPollRef.current);
      renderPollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API_BASE}/render_status?task_id=${taskId}`);
          if (statusRes.data.status === "done") {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("done");
            setProgress(null);
            setBackendJobRunning({ is_strategizing: false, is_rendering: false });
            fetchGallery();
            setActiveView("gallery");
            addLog("✅ Render complete — clips saved to the output folder. Open the Gallery tab to review.");
          } else if (statusRes.data.status === "error") {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("error");
            setBackendJobRunning({ is_strategizing: false, is_rendering: false });
            addLog(`❌ Render Error: ${statusRes.data.error}`);
          }
        } catch {
          /* poll again */
        }
      }, 2000);
    } catch {
      setStatus("error");
      setCardRenderStates(prev => ({ ...prev, [index]: "error" }));
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
    }
  };

  const renderAllClips = async (selectedIds?: number[]) => {
    beginRenderTracking({ clearLogs: true });

    const clipSettingsMap: Record<number, any> = {};
    const targetIds = (selectedIds && selectedIds.length > 0)
      ? selectedIds
      : (results?.clips || []).map((_: any, i: number) => i);

    targetIds.forEach((id: number) => {
      const { layout_mode: _unused, ...s } = getSettings(id);
      clipSettingsMap[id] = s;
    });

    try {
      await axios.post(`${API_BASE}/render_all`, {
        ...globalSettings,
        layout_mode: globalSettings.layout_mode || "portrait",
        face_track: (globalSettings.face_track ?? true),
        clip_ids: targetIds,
        titles: editedTitles,
        clip_settings: clipSettingsMap,
        session_id: sessionId,
        style_mode: styleMode,
        style_allowlist: styleAllowlist,
        fixed_style: fixedStyle
      });

      if (renderPollRef.current) clearInterval(renderPollRef.current);
      renderPollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API_BASE}/status`);
          setBackendJobRunning({
            is_strategizing: !!statusRes.data.is_strategizing,
            is_rendering: !!statusRes.data.is_rendering,
          });
          if (!statusRes.data.is_rendering) {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("done");
            setProgress(null);
            fetchGallery();
            setActiveView("gallery");
            addLog("✅ All clips rendered — saved to the output folder. Open the Gallery tab to review.");
          }
        } catch {
          /* poll again */
        }
      }, 2000);
    } catch {
      setStatus("error");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
    }
  };

  /* ── Transcript Editor Logic ──────────────────────── */
  const [excludedSentences, setExcludedSentences] = useState<Record<number, {text: string, start_idx: number, end_idx: number}[]>>({});

  const getClipSentences = useMemo(() => (clipIdx: number) => {
    if (!results?.clips?.[clipIdx] || !results?.word_timestamps) return [];
    const clip = results.clips[clipIdx];
    const words = results.word_timestamps;

    // Find words in clip range
    const clipSt = parseFloat(clip.start_time || 0);
    const clipEt = parseFloat(clip.end_time || 0);
    const clipWords = words.map((w: any, i: number) => ({ ...w, idx: i }))
      .filter((w: any) => {
        if (clip.is_stitched && clip.segments && clip.segments.length > 0) {
          return clip.segments.some((seg: any) =>
            w.start >= parseFloat(seg.start_time) - 0.5 &&
            w.end <= parseFloat(seg.end_time) + 0.5
          );
        }
        return w.start >= clipSt - 0.5 && w.end <= clipEt + 0.5;
      });

    // Group into sentences by punctuation and pauses
    const sentences = [];
    let currentSentence: any[] = [];

    for (let i = 0; i < clipWords.length; i++) {
      const w = clipWords[i];
      currentSentence.push(w);
      const endsSentence = /[.!?।|]/.test(w.word);
      let pauseAfter = false;
      if (i + 1 < clipWords.length) {
        pauseAfter = (clipWords[i+1].start - w.end) > 0.5;
      }

      if (endsSentence || pauseAfter || currentSentence.length >= 20) {
        sentences.push({
          text: currentSentence.map((cw: any) => cw.word).join(" "),
          start_idx: currentSentence[0].idx,
          end_idx: currentSentence[currentSentence.length - 1].idx
        });
        currentSentence = [];
      }
    }
    if (currentSentence.length > 0) {
      sentences.push({
        text: currentSentence.map((cw: any) => cw.word).join(" "),
        start_idx: currentSentence[0].idx,
        end_idx: currentSentence[currentSentence.length - 1].idx
      });
    }
    return sentences;
  }, [results]);

  const sortedClips = useMemo(() => {
    if (!results?.clips) return [];
    const list = results.clips.map((clip: any, idx: number) => ({ ...clip, originalIdx: idx }));
    if (sortBy === "score") {
      list.sort((a: any, b: any) => (b.virality_score || b.score || 0) - (a.virality_score || a.score || 0));
    } else if (sortBy === "energy") {
      list.sort((a: any, b: any) => (b.energy_score || 0) - (a.energy_score || 0));
    } else if (sortBy === "duration") {
      const getDur = (c: any) => c.duration || (parseFloat(c.end_time || 0) - parseFloat(c.start_time || 0));
      list.sort((a: any, b: any) => getDur(b) - getDur(a));
    } else if (sortBy === "hook") {
      list.sort((a: any, b: any) => (b.hook_score || 0) - (a.hook_score || 0));
    }
    return list;
  }, [results?.clips, sortBy]);

  const toggleSentence = (clipIdx: number, sentence: any) => {
    setExcludedSentences(prev => {
      const current = prev[clipIdx] || [];
      const exists = current.find(s => s.start_idx === sentence.start_idx);
      if (exists) {
        return { ...prev, [clipIdx]: current.filter(s => s.start_idx !== sentence.start_idx) };
      } else {
        return { ...prev, [clipIdx]: [...current, sentence] };
      }
    });
  };

  const activeSettings = selectedClip !== null ? getSettings(selectedClip) : globalSettings;

  // Unified setter: writes to the selected clip if one is open, otherwise to the
  // global defaults. Replaces the two duplicate settings panels with one.
  const applySetting = (key: string, value: any) => {
    if (selectedClip !== null) updateSetting(selectedClip, key, value);
    else updateGlobalSetting(key, value);
  };
  const applyPreset = (presetKey: string) => {
    applySetting("template", presetKey);
    const preset = STYLE_PRESETS[presetKey];
    if (!preset) return;
    Object.entries(preset.changes).forEach(([k, v]) => applySetting(k, v));
  };

  const getAllowedSeeds = () => {
    return STYLE_SEEDS.filter(seed => {
      const c = seed.changes;
      const hAllowed = !styleAllowlist.header || styleAllowlist.header.length === 0 || styleAllowlist.header.includes(c.header_style as string);
      const tAllowed = !styleAllowlist.title || styleAllowlist.title.length === 0 || styleAllowlist.title.includes(c.title_style as string);
      const capAllowed = !styleAllowlist.caption || styleAllowlist.caption.length === 0 || styleAllowlist.caption.includes(c.caption_style as string);
      const hkAllowed = !styleAllowlist.hook || styleAllowlist.hook.length === 0 || styleAllowlist.hook.includes(c.hook_style as string);
      return hAllowed && tAllowed && capAllowed && hkAllowed;
    });
  };

  const randomizeAllSeeds = () => {
    if (!results?.clips?.length) return;
    if (styleMode === "fixed") {
      setRenderSettings(prev => {
        const updated = { ...prev };
        results.clips.forEach((_: any, idx: number) => {
          updated[idx] = {
            ...(updated[idx] || DEFAULT_SETTINGS),
            header_style: fixedStyle.header,
            title_style: fixedStyle.title,
            caption_style: fixedStyle.caption,
            hook_style: fixedStyle.hook,
          };
        });
        return updated;
      });
      return;
    }

    const allowed = getAllowedSeeds();
    const pool = allowed.length > 0 ? allowed : STYLE_SEEDS;
    const seedIdsPool = pool.map(s => s.id);

    const seedAssignment: Record<number, string> = {};
    results.clips.forEach((_: any, idx: number) => {
      const rSeedId = seedIdsPool[Math.floor(Math.random() * seedIdsPool.length)];
      seedAssignment[idx] = rSeedId;
    });

    setClipSeedIds(seedAssignment);
    setRenderSettings(prev => {
      const updated = { ...prev };
      results.clips.forEach((_: any, idx: number) => {
        const seed = pool.find(s => s.id === seedAssignment[idx]);
        if (seed) {
          updated[idx] = { ...(updated[idx] || globalSettings), ...(seed.changes as any) };
        }
      });
      return updated;
    });
  };

  const randomizeClipSeed = (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (styleMode === "fixed") {
      setRenderSettings(prev => ({
        ...prev,
        [clipIdx]: {
          ...(prev[clipIdx] || globalSettings),
          header_style: fixedStyle.header,
          title_style: fixedStyle.title,
          caption_style: fixedStyle.caption,
          hook_style: fixedStyle.hook,
        }
      }));
      return;
    }

    const allowed = getAllowedSeeds();
    const pool = allowed.length > 0 ? allowed : STYLE_SEEDS;
    const newSeed = pool[Math.floor(Math.random() * pool.length)];
    if (!newSeed) return;

    setClipSeedIds(prev => ({ ...prev, [clipIdx]: newSeed.id }));
    setRenderSettings(prev => {
      return {
        ...prev,
        [clipIdx]: { ...(prev[clipIdx] || globalSettings), ...(newSeed.changes as any) }
      };
    });
  };

  const deleteRenderedClip = async (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const clip = results?.clips?.[clipIdx];
    if (!clip?.rendered_filename) return;
    const parts = (clip.rendered_filename as string).split("/");
    if (parts.length < 2) {
      addLog("Cannot delete: clip path is missing video ID.");
      return;
    }
    const videoId = parts[parts.length - 2];
    const filename = parts[parts.length - 1];
    showConfirm("Delete Clip", `Delete "${filename}"? This removes it from disk and cannot be undone.`, async () => {
      try {
        const res = await fetch(`${API_BASE}/clips/${videoId}/${encodeURIComponent(filename)}`, { method: "DELETE" });
        if (!res.ok) { addLog("Delete failed — check Drive connection."); return; }
        setResults((prev: any) => {
          if (!prev) return prev;
          const clips = prev.clips.map((c: any, i: number) =>
            i === clipIdx ? { ...c, rendered_filename: undefined } : c
          );
          return { ...prev, clips };
        });
      } catch {
        addLog("Delete failed — check Drive connection.");
      }
    });
  };

  return (
    <ErrorBoundary>
      <SaaSStudio
        url={url}
        setUrl={setUrl}
        fileInputRef={fileInputRef as any}
        handleFileUpload={handleFileUpload}
        uploading={uploading}
        status={status}
        startStrategize={(urlToUse) => startStrategize(urlToUse || url)}
        llmLabel={llmLabel}
        setLlmLabel={setLlmLabel}
        whisperLabel={whisperLabel}
        setWhisperLabel={setWhisperLabel}
        selectedCampaignId={selectedCampaignId}
        setSelectedCampaignId={setSelectedCampaignId}
        campaignBrief={campaignBrief}
        setCampaignBrief={setCampaignBrief}
        allowNaturalRecomposition={allowNaturalRecomposition}
        setAllowNaturalRecomposition={setAllowNaturalRecomposition}
        catalogData={catalogData}
        campaigns={campaigns}
        activeCampaignName={activeProfile?.name || activeCampaignId.replace(/-/g, " ").toUpperCase()}
        activeCampaignId={activeCampaignId}
        activeProfile={activeProfile}
        onSelectCampaign={handleSelectCampaign}
        onOpenCampaignModal={() => setShowCampaignModal(true)}
        onOpenOutputDir={handleOpenOutputDir}
        onExportPackage={handleExportPackage}
        results={results}
        renderClip={renderClip}
        renderAllClips={renderAllClips}
        activeView={activeView}
        setActiveView={setActiveView}
        gallery={gallery}
        filteredGallery={filteredGallery}
        galleryFilter={galleryFilter}
        setGalleryFilter={setGalleryFilter}
        sortedClips={sortedClips}
        sortBy={sortBy}
        setSortBy={setSortBy}
        gallerySessionMode={gallerySessionMode}
        setGallerySessionMode={setGallerySessionMode}
        openEditor={openEditor}
        onOpenStylePanel={() => setShowStylePanel(true)}
        onOpenWatermarkModal={openWatermarkModal}
        captionsBelow={(activeSettings.caption_pos || "below") === "below"}
        onToggleCaptionsBelow={(v) => updateGlobalSetting("caption_pos", v ? "below" : "bottom")}
        layoutMode={activeSettings.layout_mode || "portrait"}
        onToggleLayoutMode={(m) => updateGlobalSetting("layout_mode", m)}
        faceTrack={(activeSettings.face_track ?? true) === true}
        onToggleFaceTrack={(v) => updateGlobalSetting("face_track", v)}
        forceHeaderText={activeSettings.force_header_text}
        onForceHeaderTextChanged={(v) => updateGlobalSetting("force_header_text", v)}
        logs={logs}
        logEndRef={logEndRef}
        progress={progress}
        batchRun={batchRun}
        onStartBatch={startBatchFromUI}
        setShowSettings={setShowSettings}
        backendStatus={backendStatus}
        queueState={queueState}
        setQueueState={setQueueState}
        addLog={addLog}
        API_BASE={API_BASE}
        onCancelProcess={handleCancel}
        onResetSession={handlePurge}
        showPurgeModal={showPurgeModal}
        setShowPurgeModal={setShowPurgeModal}
        confirmPurge={confirmPurge}
      />

      <CampaignModal
        isOpen={showCampaignModal}
        onClose={() => setShowCampaignModal(false)}
        campaigns={campaigns}
        activeCampaignId={activeCampaignId}
        activeProfile={activeProfile}
        onSelectCampaign={handleSelectCampaign}
        onCampaignCreated={async () => {
          try {
            const res = await axios.get(`${API_BASE}/campaigns`);
            setCampaigns(res.data.campaigns || []);
            await fetchActiveCampaign();
          } catch {}
        }}
        API_BASE={API_BASE}
      />

      {/* PREMIUM GOOGLE DRIVE SESSION RESTORE MODAL */}
      {showRestoreModal && (
        <div 
          className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4"
          onClick={() => setShowRestoreModal(false)}
        >
          <div 
            className="bg-white border border-slate-200 rounded-2xl shadow-md max-w-md w-full p-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setShowRestoreModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-indigo-50 rounded-xl flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-800">Restore Previous Session?</h3>
                <p className="text-xs text-slate-500">Cached session found in local storage</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 mb-6">
              A previously completed strategy session for this video exists in your local cache. Would you like to restore it to save processing time and API usage?
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => restoreSession(pendingRestoreUrl)}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2.5 rounded-xl text-sm transition-all shadow-md flex items-center justify-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4" />
                Yes, Restore
              </button>
              <button
                onClick={() => {
                  setShowRestoreModal(false);
                  startStrategize(pendingRestoreUrl);
                }}
                className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold py-2.5 rounded-xl text-sm transition-all border border-slate-200 flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                No, Start Fresh
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Global auto-apply watermark settings modal ── */}
      {showWatermarkModal && (
        <div
          className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4"
          onClick={() => setShowWatermarkModal(false)}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl shadow-md max-w-md w-full p-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setShowWatermarkModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-indigo-50 rounded-xl flex items-center justify-center">
                <Wand2 className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-800">Global Watermark</h3>
                <p className="text-xs text-slate-500">Auto-applied to every clip you render</p>
              </div>
            </div>

            <label className="flex items-center gap-3 mb-4 cursor-pointer">
              <input
                type="checkbox"
                checked={watermarkCfg.enabled}
                onChange={(e) => setWatermarkCfg({ ...watermarkCfg, enabled: e.target.checked })}
                className="w-5 h-5 accent-indigo-600"
              />
              <span className="text-sm font-semibold text-slate-700">Enable watermark on new renders</span>
            </label>

            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide mb-1.5">
              Watermark PNG
            </label>
            <input
              type="file"
              accept="image/png"
              onChange={(e) => setWmConfigFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-indigo-50 file:text-indigo-600 file:font-bold file:text-xs hover:file:bg-indigo-100 mb-1.5"
            />
            <p className="text-xs text-slate-400 mb-4">
              {wmConfigFile
                ? `Selected: ${wmConfigFile.name}`
                : watermarkCfg.has_image
                  ? "Current image saved — pick a new one to replace it."
                  : "No image saved yet. Transparent PNG recommended."}
            </p>

            <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide mb-1.5">Position</label>
            <select
              value={watermarkCfg.position}
              onChange={(e) => setWatermarkCfg({ ...watermarkCfg, position: e.target.value })}
              className="w-full mb-4 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="bottom-center">Bottom Center (default)</option>
              <option value="bottom-left">Bottom Left</option>
              <option value="bottom-right">Bottom Right</option>
              <option value="top-left">Top Left</option>
              <option value="top-right">Top Right</option>
              <option value="top-center">Top Center</option>
              <option value="center">Center</option>
            </select>

            <label className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wide mb-1.5">
              <span>Opacity</span>
              <span className="text-indigo-600">{Math.round(watermarkCfg.opacity * 100)}%</span>
            </label>
            <input
              type="range"
              min={5}
              max={100}
              value={Math.round(watermarkCfg.opacity * 100)}
              onChange={(e) => setWatermarkCfg({ ...watermarkCfg, opacity: Number(e.target.value) / 100 })}
              className="w-full mb-5 accent-indigo-600"
            />

            <div className="flex gap-3">
              <button
                onClick={saveWatermarkConfig}
                disabled={watermarkSaving}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold py-2.5 rounded-xl text-sm transition-all shadow-md flex items-center justify-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4" />
                {watermarkSaving ? "Saving…" : "Save"}
              </button>
              {watermarkCfg.has_image && (
                <button
                  onClick={clearWatermark}
                  className="flex-1 bg-red-50 hover:bg-red-100 text-red-600 font-bold py-2.5 rounded-xl text-sm transition-all border border-red-200 flex items-center justify-center gap-2"
                >
                  <Trash2 className="w-4 h-4" />
                  Remove
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Chunk D3 — Post-render editor modal (trim / watermark / crop) ── */}
      {editorOp && editorTarget && (
        <div className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4" onClick={closeEditor}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-md max-w-md w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2 capitalize">
                {editorOp === "trim" && <Scissors className="w-5 h-5 text-indigo-600" />}
                {editorOp === "watermark" && <Wand2 className="w-5 h-5 text-indigo-600" />}
                {editorOp === "crop" && <Crop className="w-5 h-5 text-indigo-600" />}
                {editorOp} clip
              </h3>
              <button onClick={closeEditor} className="text-slate-400 hover:text-slate-700 transition-colors" aria-label="Close">
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-[11px] text-slate-500 mb-4 truncate">Source: {editorTarget.filename}</p>

            {/* ── TRIM ── */}
            {editorOp === "trim" && (
              <div className="space-y-3">
                <video
                  key={editorTarget.url}
                  className="w-full max-h-48 bg-slate-900 rounded-lg mb-2"
                  src={editorTarget.url}
                  controls
                  muted
                  ref={el => setTrimSeekBy(el)}
                />
                <p className="text-[10px] text-slate-500">
                  Click the video, then press <kbd className="bg-slate-100 border border-slate-200 rounded px-1">[</kbd> to set Start, <kbd className="bg-slate-100 border border-slate-200 rounded px-1">]</kbd> to set End.
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] uppercase font-bold text-slate-500">Start (s)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={trimStart}
                      onChange={e => setTrimStart(parseFloat(e.target.value) || 0)}
                      className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2 outline-none font-medium"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase font-bold text-slate-500">End (s)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={trimEnd}
                      onChange={e => setTrimEnd(parseFloat(e.target.value) || 0)}
                      className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2 outline-none font-medium"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => { if (trimSeekBy) { const t = trimSeekBy.currentTime; setTrimStart(Math.round(t * 10) / 10); } }}
                    className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-bold py-1.5 rounded-md border border-slate-200 transition-all"
                  >
                    [ Set Start = here
                  </button>
                  <button
                    onClick={() => { if (trimSeekBy) { const t = trimSeekBy.currentTime; setTrimEnd(Math.round(t * 10) / 10); } }}
                    className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-bold py-1.5 rounded-md border border-slate-200 transition-all"
                  >
                    Set End = here ]
                  </button>
                </div>
              </div>
            )}

            {/* ── WATERMARK ── */}
            {editorOp === "watermark" && (
              <div className="space-y-3">
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">PNG file</label>
                  <input
                    type="file"
                    accept="image/png"
                    onChange={e => setWatermarkFile(e.target.files?.[0] || null)}
                    className="w-full text-xs text-slate-700 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:bg-indigo-50 file:text-indigo-700 file:font-bold file:cursor-pointer hover:file:bg-indigo-100"
                  />
                  {watermarkFile && (
                    <div className="mt-2 flex items-center gap-3 bg-slate-50 border border-slate-200 rounded-lg p-2">
                      <img
                        src={URL.createObjectURL(watermarkFile)}
                        alt="watermark preview"
                        className="w-16 h-16 object-contain bg-[repeating-conic-gradient(#e2e8f0_0_25%,#fff_0_50%)] bg-size-4 rounded"
                      />
                      <div className="text-[10px] text-slate-600">
                        <div className="font-bold truncate max-w-[180px]">{watermarkFile.name}</div>
                        <div className="text-slate-500">{(watermarkFile.size / 1024).toFixed(1)} KB</div>
                      </div>
                      <button
                        onClick={() => setWatermarkFile(null)}
                        className="ml-auto text-slate-400 hover:text-rose-600 transition-colors"
                        title="Remove"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </div>
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Position</label>
                  <select
                    value={watermarkPosition}
                    onChange={e => setWatermarkPosition(e.target.value as typeof watermarkPosition)}
                    className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2 outline-none font-medium"
                  >
                    <option value="bottom-right">Bottom Right</option>
                    <option value="bottom-left">Bottom Left</option>
                    <option value="top-right">Top Right</option>
                    <option value="top-left">Top Left</option>
                  </select>
                </div>
              </div>
            )}

            {/* ── CROP ── */}
            {editorOp === "crop" && (
              <div className="space-y-3">
                <label className="text-[10px] uppercase font-bold text-slate-500">Target aspect ratio</label>
                <div className="grid grid-cols-3 gap-2">
                  {(["9:16", "1:1", "4:5"] as const).map(r => (
                    <button
                      key={r}
                      onClick={() => setCropRatio(r)}
                      className={`py-2.5 rounded-md text-sm font-bold border transition-all ${cropRatio === r ? "bg-indigo-600 text-white border-indigo-600" : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"}`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* ── RESULT ── */}
            {editorLoading && (
              <div className="mt-4 text-xs text-indigo-700 font-bold flex items-center gap-2">
                <span className="inline-block w-3 h-3 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
                Running ffmpeg…
              </div>
            )}
            {editorError && (
              <div className="mt-3 bg-rose-50 border border-rose-200 rounded-lg p-2.5 text-[11px] text-rose-700 font-medium">
                {editorError}
              </div>
            )}
            {editorData && (
              <div className="mt-3 bg-emerald-50 border border-emerald-200 rounded-lg p-2.5 text-[11px] text-emerald-700 font-medium">
                ✅ Saved as {editorData.out_filename}. Will appear in gallery on next refresh.
              </div>
            )}

            <div className="flex gap-3 mt-5">
              <button
                onClick={submitEditor}
                disabled={editorLoading}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-2.5 rounded-xl text-sm transition-all shadow-md flex items-center justify-center gap-2"
              >
                {editorLoading ? "Working…" : `Apply ${editorOp}`}
              </button>
              <button
                onClick={closeEditor}
                disabled={editorLoading}
                className="flex-1 bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-700 font-bold py-2.5 rounded-xl text-sm transition-all border border-slate-200 flex items-center justify-center gap-2"
              >
                <X className="w-4 h-4" /> Cancel
              </button>
            </div>
            {editorData && editorData.out_url && (
              <a
                href={editorData.out_url.startsWith('http') ? editorData.out_url : `${API_BASE.replace('/api', '')}${editorData.out_url}`}
                target="_blank"
                rel="noreferrer"
                className="block mt-2 w-full text-center bg-slate-50 hover:bg-slate-100 text-indigo-600 text-[11px] font-bold py-1.5 rounded-md border border-slate-200 transition-all"
              >
                Preview new file
              </a>
            )}
          </div>
        </div>
      )}

      {showSettings && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-[200] flex items-center justify-center p-4" onClick={() => setShowSettings(false)}>
          <div className="bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl w-[640px] max-w-[95vw] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
              <h3 className="text-lg font-extrabold text-white flex items-center gap-2">
                <Settings2 className="w-5 h-5 text-indigo-400" />
                Studio Settings & AI Engine
              </h3>
              <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800/80">
                <button 
                  onClick={() => setSettingsTab("models")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${settingsTab === "models" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                >
                  AI & Engine
                </button>
                <button 
                  onClick={() => setSettingsTab("folders")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${settingsTab === "folders" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                >
                  Folders & Storage
                </button>
                <button 
                  onClick={() => setSettingsTab("api")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${settingsTab === "api" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                >
                  API Keys
                </button>
              </div>
            </div>
            
            <div className="p-6 max-h-[460px] overflow-y-auto custom-scrollbar space-y-4">
              {/* TAB 1: AI & MODELS */}
              {settingsTab === "models" && (
                <div className="space-y-5">
                  <div className="space-y-1.5">
                    <label className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-indigo-400" /> Main AI Director Model
                    </label>
                    <p className="text-[11px] text-slate-400">
                      The core intelligence engine responsible for transcript analysis, topic segmentation, and viral scoring.
                    </p>
                    <select
                      value={llmLabel}
                      onChange={(e) => setLlmLabel(e.target.value)}
                      className="w-full mt-1.5 bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                    >
                      {Object.entries(
                        catalogData.llm_catalog.reduce((acc: Record<string, any[]>, m: any) => {
                          const g = (m as any).group || "Local Models (12-14B)";
                          (acc[g] = acc[g] || []).push(m);
                          return acc;
                        }, {})
                      ).map(([groupName, models]) => (
                        <optgroup key={groupName} label={groupName} className="bg-slate-900 text-slate-300">
                          {(models as any[]).map((m: any) => (
                            <option key={m.label} value={m.label} className="bg-slate-900 text-white">{m.label}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5 pt-3 border-t border-slate-800/80">
                    <label className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                      <Film className="w-3.5 h-3.5 text-emerald-400" /> Transcription Engine
                    </label>
                    <p className="text-[11px] text-slate-400">
                      Whisper model used to extract word-level timestamps and captions.
                    </p>
                    <select
                      value={whisperLabel}
                      onChange={(e) => setWhisperLabel(e.target.value)}
                      className="w-full mt-1.5 bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                    >
                      {catalogData.whisper_catalog.map((m: any) => (
                        <option key={m.label} value={m.label} className="bg-slate-900 text-white">{m.label}</option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5 pt-3 border-t border-slate-800/80">
                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-xs font-bold text-slate-300 uppercase tracking-wider">Natural Recomposition</label>
                        <p className="text-[11px] text-slate-400">Allow AI to stitch non-contiguous thoughts into high-retention composite hooks.</p>
                      </div>
                      <input
                        type="checkbox"
                        checked={allowNaturalRecomposition}
                        onChange={(e) => setAllowNaturalRecomposition(e.target.checked)}
                        className="w-4 h-4 rounded accent-indigo-600 cursor-pointer"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: FOLDERS & STORAGE */}
              {settingsTab === "folders" && (
                <div className="space-y-6">
                  {/* Folders Overview */}
                  <div className="space-y-3">
                    <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-xs font-bold text-slate-200">📥 Batch Watch Folder (Input)</div>
                          <div className="text-[11px] text-slate-400">Videos dropped here are automatically queued for extraction. Or just use Browse Video File(s) to pick videos directly.</div>
                        </div>
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              const res = await axios.post(`${API_BASE}/queue/pick_folder`);
                              const chosen = res.data?.path || res.data?.watch_dir;
                              if (chosen) {
                                setWatchDirInput(chosen);
                                setQueueState((prev) => ({ ...prev, queue_watch_dir: chosen }));
                                addLog(`📂 Batch folder set to: ${chosen}`);
                              } else {
                                addLog(`❌ Folder picker: ${res.data?.reason || "cancelled"}`);
                              }
                            } catch {
                              addLog("❌ Folder picker failed");
                            }
                          }}
                          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-bold transition-all"
                        >
                          Pick Folder
                        </button>
                      </div>
                      <div className="font-mono text-xs text-indigo-300 bg-slate-900 px-3 py-2 rounded-xl border border-slate-800 truncate">
                        {watchDirInput || "Default: ./watch/"}
                      </div>
                    </div>

                    <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-xs font-bold text-slate-200">📤 Render Output Folder (Export)</div>
                          <div className="text-[11px] text-slate-400">Completed MP4s, captions, and sidecars are exported here.</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleOpenOutputDir()}
                          className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold transition-all shadow-md flex items-center gap-1"
                        >
                          <Folder className="w-3.5 h-3.5" /> Open Folder
                        </button>
                      </div>
                      <div className="font-mono text-xs text-emerald-400 bg-slate-900 px-3 py-2 rounded-xl border border-slate-800 truncate">
                        ./output/
                      </div>
                    </div>
                  </div>

                  {/* Local Models */}
                  <div>
                    <h4 className="text-xs font-extrabold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2 mb-3">Local GGUF Models</h4>
                    {storageInfo.models.length === 0 && <p className="text-xs text-slate-500 italic">No local GGUF models downloaded.</p>}
                    <div className="space-y-2">
                      {storageInfo.models.map(m => (
                        <div key={m.filename} className="flex items-center justify-between bg-slate-950 border border-slate-800 p-3 rounded-xl">
                          <div>
                            <div className="text-xs font-bold text-slate-200">{m.filename}</div>
                            <div className="text-[11px] text-slate-500 font-mono">{m.size_mb} MB</div>
                          </div>
                          <button onClick={() => deleteModel(m.filename)} className="text-rose-400 hover:bg-rose-950/30 p-2 rounded-lg text-xs font-bold border border-rose-500/20">Delete</button>
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  {/* Saved Sessions */}
                  <div>
                    <h4 className="text-xs font-extrabold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2 mb-3">Saved Sessions</h4>
                    {storageInfo.sessions.length === 0 && <p className="text-xs text-slate-500 italic">No saved sessions found.</p>}
                    <div className="space-y-3">
                      {storageInfo.sessions.map(s => (
                        <div key={s.video_id} className="flex flex-col bg-slate-950 border border-slate-800 p-3 rounded-2xl gap-2 shadow-sm">
                          <div className="flex justify-between items-start">
                            <div className="max-w-[80%] space-y-1">
                              <div className="text-xs font-bold text-slate-200 truncate" title={s.url || s.video_id}>
                                {s.url ? s.url : `Session: ${s.video_id}`}
                              </div>
                              <div className="flex gap-3 text-[10px] text-slate-400 font-mono">
                                <span>📁 {s.size_mb} MB</span>
                                <span>🎬 {s.clips_count} Clips</span>
                                <span>⏱️ {s.duration ? `${Math.round(s.duration)}s` : 'Unknown'}</span>
                              </div>
                            </div>
                            <button onClick={() => deleteSession(s.video_id)} className="text-rose-400 hover:bg-rose-950/30 p-1.5 rounded-lg text-xs font-bold border border-rose-500/20 transition-all">
                              Delete
                            </button>
                          </div>
                          {s.url && (
                            <button
                              onClick={async () => {
                                setShowSettings(false);
                                setUrl(s.url);
                                await restoreSession(s.url);
                              }}
                              className="w-full py-2 px-3 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 rounded-xl text-xs font-bold transition-all flex items-center justify-center gap-1.5 shadow-sm"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                              Restore Session
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: API KEYS */}
              {settingsTab === "api" && (
                <div className="space-y-4">
                  <div className="bg-indigo-950/40 text-indigo-300 p-3.5 rounded-2xl text-xs font-medium border border-indigo-800/40">
                    💡 Keys are stored locally and encrypted. Each provider can hold multiple keys — stack them (one per line) and the app rotates through them automatically if one hits a rate limit.
                  </div>
                  <ApiKeysStack label="TokenRouter API Key (Qwen 3.8 Max - Fast Flagship)" placeholder="sk-mp5..." value={apiKeys.TOKENROUTER_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, TOKENROUTER_API_KEY: v }))} />
                  <ApiKeysStack label="NVIDIA API Key (Ultra-Fast NIM)" placeholder="nvapi-..." value={apiKeys.NVIDIA_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, NVIDIA_API_KEY: v }))} />
                  <ApiKeysStack label="Groq API Key (Llama 3.3 70B)" placeholder="gsk_..." value={apiKeys.GROQ_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, GROQ_API_KEY: v }))} />
                  <ApiKeysStack label="OpenRouter API Key" placeholder="sk-or-v1-..." value={apiKeys.OPENROUTER_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, OPENROUTER_API_KEY: v }))} />
                  <ApiKeysStack label="Gemini API Key" placeholder="AIzaSy..." value={apiKeys.GEMINI_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, GEMINI_API_KEY: v }))} />
                  <ApiKeysStack label="GLM API Key (Zhipu)" placeholder="paste key..." value={apiKeys.GLM_API_KEY} onChange={(v) => setApiKeys(prev => ({ ...prev, GLM_API_KEY: v }))} />
                  <button onClick={saveSettings} className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-extrabold py-3 rounded-2xl mt-4 transition-all shadow-lg shadow-indigo-500/20 text-xs">
                    Save API Keys
                  </button>
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-slate-800 bg-slate-950/60 flex justify-end">
              <button onClick={() => setShowSettings(false)} className="px-6 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-extrabold rounded-xl text-xs transition-colors">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      {showStylePanel && (
        <StylePanelModal
          isOpen={showStylePanel}
          onClose={() => setShowStylePanel(false)}
          styleMode={styleMode}
          styleAllowlist={styleAllowlist}
          fixedStyle={fixedStyle}
          onSave={saveStyleSelection}
        />
      )}
    </ErrorBoundary>
  );
}
