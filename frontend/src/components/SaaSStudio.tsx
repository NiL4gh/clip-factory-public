"use client";

import { useState, useRef, useEffect } from "react";
import { 
  Zap, Film, Scissors, Sparkles, Activity, Folder, Wand2, Crop, 
  Trash2, RefreshCw, CheckCircle2, ArrowRight, Settings2, Play, Square, Eye, EyeOff, Search 
} from "lucide-react";
import axios from "axios";
import { StorageManager } from "./StorageManager";
import { Sidebar } from "./ui/sidebar";
import { Header } from "./Header";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { LineStrategyInspector } from "./editor/LineStrategyInspector";
import { WhopPublisher } from "./business/WhopPublisher";

interface SaaSStudioProps {
  url: string;
  setUrl: (v: string) => void;
  fileInputRef: any;
  handleFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  uploading: boolean;
  status: string;
  startStrategize: (urlToUse?: string) => void;
  llmLabel: string;
  setLlmLabel: (v: string) => void;
  whisperLabel: string;
  setWhisperLabel: (v: string) => void;
  selectedCampaignId: string;
  setSelectedCampaignId: (v: string) => void;
  campaignBrief: string;
  setCampaignBrief: (v: string) => void;
  allowNaturalRecomposition: boolean;
  setAllowNaturalRecomposition: (v: boolean) => void;
  catalogData: { llm_catalog: any[]; whisper_catalog: any[]; bgm_genres: string[] };
  campaigns: { id: string; name: string; brief: string }[];
  activeCampaignName?: string;
  activeProfile?: any;
  onOpenCampaignModal?: () => void;
  onOpenOutputDir?: (videoId?: string, folderPath?: string) => void;
  onExportPackage?: () => void;
  results: any;
  renderClip: (idx: number) => void;
  renderAllClips: (selectedIds?: number[]) => void;
  activeView: "workspace" | "gallery" | "whop" | "storage";
  setActiveView: (v: "workspace" | "gallery" | "whop" | "storage") => void;
  gallery: any[];
  filteredGallery?: any[];
  galleryFilter?: "all" | "today" | "over30" | "under30";
  setGalleryFilter?: (v: "all" | "today" | "over30" | "under30") => void;
  sortedClips?: any[];
  sortBy?: "score" | "energy" | "duration" | "hook";
  setSortBy?: (v: "score" | "energy" | "duration" | "hook") => void;
  gallerySessionMode: "current" | "all";
  setGallerySessionMode: (v: "current" | "all") => void;
  openEditor: (op: "trim" | "watermark" | "crop", item: any) => void;
  logs: string[];
  logEndRef: React.RefObject<HTMLDivElement | null>;
  progress: any | null;
  batchRun?: {
    total: number;
    done: number;
    failed: number;
    currentId?: string | null;
    currentFile?: string | null;
    currentStatus?: string | null;
  } | null;
  onStartBatch?: () => void;
  setShowSettings: (v: boolean) => void;
  backendStatus: "connected" | "disconnected" | "checking";
  queueState: any;
  setQueueState: React.Dispatch<React.SetStateAction<any>>;
  addLog: (msg: string) => void;
  API_BASE: string;
  activeCampaignId?: string;
  onSelectCampaign?: (id: string) => Promise<void>;
  onCancelProcess?: () => void;
  onResetSession?: () => void;
  showPurgeModal?: boolean;
  setShowPurgeModal?: (v: boolean) => void;
  confirmPurge?: () => void;
  onOpenStylePanel?: () => void;
  onOpenWatermarkModal?: () => void;
  captionsBelow?: boolean;
  onToggleCaptionsBelow?: (v: boolean) => void;
  layoutMode?: string;
  onToggleLayoutMode?: (mode: "box" | "portrait") => void;
  faceTrack?: boolean;
  onToggleFaceTrack?: (v: boolean) => void;
  forceHeaderText?: string;
  onForceHeaderTextChanged?: (v: string) => void;
}

function ClipSegmentPreview({ clip, clipIdx, API_BASE }: { clip: any; clipIdx: number; API_BASE: string }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const start = parseFloat(clip.start_time ?? clip.start ?? 0);
  const rawEnd = parseFloat(clip.end_time ?? clip.end ?? 0);
  const end = rawEnd > start ? rawEnd : (start + (parseFloat(clip.duration) || 30));
  const mediaUrl = `${API_BASE.replace('/api', '')}/api/source_media#t=${start},${end}`;
  const thumbUrl = clip.thumbnail_url
    ? `${API_BASE.replace('/api', '')}${clip.thumbnail_url}`
    : `${API_BASE.replace('/api', '')}/thumbs/thumb_${clipIdx}.jpg`;

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      videoRef.current.currentTime = start;
      videoRef.current.play().catch(() => {});
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current && videoRef.current.currentTime >= end) {
      videoRef.current.pause();
      videoRef.current.currentTime = start;
      setIsPlaying(false);
    }
  };

  return (
    <div className="relative aspect-video bg-slate-950 rounded-2xl overflow-hidden border border-slate-800 shrink-0 w-56 sm:w-64 md:w-72 group shadow-lg transition-all hover:border-slate-700">
      {isPlaying ? (
        <video
          ref={videoRef}
          src={mediaUrl}
          controls
          autoPlay
          preload="metadata"
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={handleTimeUpdate}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="relative w-full h-full cursor-pointer" onClick={() => setIsPlaying(true)}>
          <img
            src={thumbUrl}
            alt={clip.title || "Clip Thumbnail"}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            onError={(e) => {
              (e.target as HTMLElement).style.display = 'none';
              setIsPlaying(true);
            }}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent flex items-center justify-center opacity-90 group-hover:opacity-100 transition-opacity">
            <div className="w-11 h-11 rounded-full bg-indigo-600/90 text-white flex items-center justify-center shadow-lg group-hover:scale-110 group-hover:bg-indigo-500 transition-all border border-indigo-400/40 backdrop-blur-sm">
              <Play className="w-5 h-5 fill-white ml-0.5" />
            </div>
          </div>
        </div>
      )}
      <div className="absolute top-2 left-2 bg-black/80 backdrop-blur-md px-2 py-0.5 rounded-lg text-[10px] font-mono text-amber-300 border border-amber-500/30 pointer-events-none z-10 flex items-center gap-1">
        <span>⏱️</span> {start.toFixed(0)}s – {end.toFixed(0)}s
      </div>
    </div>
  );
}

export function SaaSStudio({
  url,
  setUrl,
  fileInputRef,
  handleFileUpload,
  uploading,
  status,
  startStrategize,
  llmLabel,
  setLlmLabel,
  whisperLabel,
  setWhisperLabel,
  selectedCampaignId,
  setSelectedCampaignId,
  campaignBrief,
  setCampaignBrief,
  allowNaturalRecomposition,
  setAllowNaturalRecomposition,
  catalogData,
  campaigns,
  activeCampaignName,
  activeCampaignId,
  activeProfile,
  onSelectCampaign,
  onOpenCampaignModal,
  onOpenOutputDir,
  onExportPackage,
  results,
  renderClip,
  renderAllClips,
  activeView,
  setActiveView,
  gallery,
  filteredGallery,
  galleryFilter = "all",
  setGalleryFilter,
  sortedClips,
  sortBy = "score",
  setSortBy,
  gallerySessionMode,
  setGallerySessionMode,
  openEditor,
  logs,
  logEndRef,
  progress,
  batchRun,
  onStartBatch,
  setShowSettings,
  backendStatus,
  queueState,
  setQueueState,
  addLog,
  API_BASE,
  onCancelProcess,
  onResetSession,
  showPurgeModal,
  setShowPurgeModal,
  confirmPurge,
  onOpenStylePanel,
  onOpenWatermarkModal,
  captionsBelow,
  onToggleCaptionsBelow,
  layoutMode,
  onToggleLayoutMode,
  faceTrack,
  onToggleFaceTrack,
  forceHeaderText,
  onForceHeaderTextChanged,
}: SaaSStudioProps) {
  // Videos sitting in the queue waiting for the user to press Start Batch.
  // Drives the button label + "waiting for your start" hint — the queue
  // never self-starts after upload (owner directive 2026-08-16).
  const pendingBatchCount = (queueState?.queue || []).filter(
    (i: any) => i.status === "pending"
  ).length;

  // Selective Render Queue state
  const [selectedForRender, setSelectedForRender] = useState<Set<number>>(new Set());

  // Auto-select all clips when results arrive
  useEffect(() => {
    if (results?.clips && Array.isArray(results.clips)) {
      setSelectedForRender(new Set(results.clips.map((_: any, i: number) => i)));
    } else {
      setSelectedForRender(new Set());
    }
  }, [results]);

  const toggleSelectClip = (idx: number) => {
    setSelectedForRender((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  const selectAllClips = () => {
    if (!results?.clips) return;
    setSelectedForRender(new Set(results.clips.map((_: any, i: number) => i)));
  };

  const deselectAllClips = () => {
    setSelectedForRender(new Set());
  };

  // Track which clip card has its preview player open (null = none)
  const [previewCardIdx, setPreviewCardIdx] = useState<number | null>(null);

  // Smart log scrolling state & ref
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const handleLogScroll = () => {
    if (!logContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 50;
    setUserScrolledUp(!atBottom);
  };

  useEffect(() => {
    if (!userScrolledUp && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, userScrolledUp, logEndRef]);

  // Gallery search & grouping state
  const [gallerySearch, setGallerySearch] = useState("");
  const [galleryGroupBy, setGalleryGroupBy] = useState<"none" | "video" | "topic">("none");

  const baseGallery = filteredGallery || gallery || [];
  const searchedGallery = baseGallery.filter((item: any) => {
    if (!gallerySearch.trim()) return true;
    const q = gallerySearch.toLowerCase();
    return (
      (item.filename && item.filename.toLowerCase().includes(q)) ||
      (item.title && item.title.toLowerCase().includes(q)) ||
      (item.topic && item.topic.toLowerCase().includes(q)) ||
      (item.video_id && item.video_id.toLowerCase().includes(q))
    );
  });

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-jakarta relative">
      {/* Collapsible Radix/Shadcn SaaS Navigation Drawer */}
      <Sidebar
        activeView={activeView}
        onSelectView={setActiveView}
        onOpenSettings={() => setShowSettings(true)}
        galleryCount={gallery.length}
        apiStatus={backendStatus}
        watchDir={queueState?.queue_watch_dir || ""}
        onPickFolder={async () => {
          try {
            const res = await axios.post(`${API_BASE}/queue/pick_folder`);
            const chosen = res.data?.path || res.data?.watch_dir;
            if (chosen) {
              setQueueState((prev: any) => ({ ...prev, queue_watch_dir: chosen }));
              addLog(`📂 Batch folder set to: ${chosen}`);
            }
          } catch {
            addLog("❌ Batch folder picker cancelled or failed");
          }
        }}
      />

      {/* Main SaaS Content Workspace Container */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        <Header
          apiStatus={backendStatus}
          watchDir={queueState?.queue_watch_dir || ""}
          queueState={queueState}
          extractedCount={results?.clips?.length || 0}
          galleryCount={gallery.length}
          activeCampaignName={activeCampaignName}
          onOpenCampaignModal={onOpenCampaignModal}
          llmLabel={llmLabel}
          setLlmLabel={setLlmLabel}
          llmCatalog={catalogData?.llm_catalog || []}
          onResetSession={onResetSession}
          onPickFolder={async () => {
            try {
              const res = await axios.post(`${API_BASE}/queue/pick_folder`);
              const chosen = res.data?.path || res.data?.watch_dir;
              if (chosen) {
                setQueueState((prev: any) => ({ ...prev, queue_watch_dir: chosen }));
                addLog(`📂 Batch folder set to: ${chosen}`);
              }
            } catch {
              addLog("❌ Batch folder picker cancelled");
            }
          }}
          onStartQueue={async () => {
            try {
              await axios.post(`${API_BASE}/queue/start`);
              addLog("▶ Queue processing started");
            } catch {
              addLog("❌ Failed to start queue");
            }
          }}
          onStopQueue={async () => {
            try {
              await axios.post(`${API_BASE}/queue/stop`);
              addLog("⏹ Queue processing stopped");
            } catch {
              addLog("❌ Failed to stop queue");
            }
          }}
        />

        <main className="flex-1 overflow-y-auto p-6 custom-scrollbar space-y-6">
          {/* TAB 1: EXTRACTION STUDIO */}
          {activeView === "workspace" && (
            <div className="max-w-6xl mx-auto space-y-6 animate-fadeIn">
              {/* Hero Video Input & Dropzone Panel */}
              <Card className="bg-gradient-to-br from-slate-900 via-slate-900/90 to-indigo-950/40 border-slate-800 p-6 rounded-3xl shadow-2xl relative overflow-hidden">
                <div className="flex flex-col md:flex-row items-stretch md:items-center gap-4">
                  <div className="relative flex-1 group">
                    <input
                      type="text"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && url && status === "idle" && !uploading) {
                          startStrategize(url);
                        }
                      }}
                      placeholder="Paste YouTube Video URL or Local MP4 Path (C:\videos\clip.mp4)... [Enter to extract]"
                      className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 rounded-2xl py-3.5 px-5 pl-12 text-white placeholder:text-slate-500 text-sm font-medium outline-none shadow-inner"
                    />
                    <Film className="absolute left-4 top-4 w-4 h-4 text-indigo-400" />
                  </div>
                  <input ref={fileInputRef} type="file" accept="video/*" multiple={true} className="hidden" onChange={handleFileUpload} />
                  <Button
                    variant="outline"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || status !== "idle"}
                    className="h-12 rounded-2xl px-5 border-slate-800 text-slate-300 hover:text-white"
                    title="Select one video to extract, or several videos to batch-queue them"
                  >
                    <Folder className="w-4 h-4 text-indigo-400 mr-2" />
                    {uploading ? "Uploading..." : "Browse Video File(s)"}
                  </Button>
                  <Button
                    variant="gradient"
                    onClick={() => {
                      if (pendingBatchCount > 0) {
                        onStartBatch?.();
                      } else {
                        startStrategize(url);
                      }
                    }}
                    disabled={uploading || status === "strategizing" || (pendingBatchCount === 0 && !url)}
                    className="h-12 rounded-2xl px-8 text-sm font-extrabold"
                  >
                    <Zap className="w-4 h-4 mr-2 fill-white" />
                    {status === "strategizing"
                      ? (batchRun ? `Batch ${Math.min(batchRun.done + 1, batchRun.total)}/${batchRun.total}` : "Extracting...")
                      : pendingBatchCount > 0
                        ? `Start Batch (${pendingBatchCount} video${pendingBatchCount === 1 ? "" : "s"})`
                        : "Extract Viral Clips with AI"}
                  </Button>

                  {pendingBatchCount > 0 && status !== "strategizing" && (
                    <span className="text-xs font-bold text-indigo-300/80 px-1 hidden md:inline">
                      Queued — waiting for your start
                    </span>
                  )}

                  {(status === "strategizing" || pendingBatchCount > 0) && onCancelProcess && (
                    <Button
                      variant="destructive"
                      onClick={onCancelProcess}
                      className="h-12 rounded-2xl px-5 text-sm font-extrabold shadow-lg shadow-rose-500/20"
                    >
                      <Square className="w-4 h-4 mr-2 fill-white" />
                      {batchRun ? "Stop Batch" : pendingBatchCount > 0 ? "Clear Queued Videos" : "Stop Process"}
                    </Button>
                  )}
                </div>

                {/* Active Campaign Environment Rules Banner */}
                <div className="mt-4 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2 text-slate-300">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="font-extrabold text-white">Active AI Environment:</span>
                    <select
                      value={selectedCampaignId || activeCampaignId || (campaigns[0]?.id ?? "")}
                      onChange={async (e) => {
                        const val = e.target.value;
                        setSelectedCampaignId(val);
                        if (onSelectCampaign) {
                          await onSelectCampaign(val);
                        }
                      }}
                      className="bg-slate-950 border border-slate-700 hover:border-indigo-500 rounded-xl px-3 py-1.5 text-xs font-extrabold text-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 cursor-pointer transition-all"
                    >
                      {campaigns.length > 0 ? (
                        campaigns.map((c) => (
                          <option key={c.id} value={c.id} className="bg-slate-900 text-white">
                            {c.name}
                          </option>
                        ))
                      ) : (
                        <option value="" className="bg-slate-900 text-white">
                          {activeCampaignName || "Default AI Extraction"}
                        </option>
                      )}
                    </select>
                    {activeProfile?.negative_filters && (
                      <span className="text-slate-500 hidden lg:inline">
                        • Excluding {activeProfile.negative_filters.slice(0, 2).join(", ")}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={onOpenCampaignModal}
                    className="text-xs text-indigo-400 hover:text-indigo-300 font-bold underline cursor-pointer flex items-center gap-1"
                  >
                    <span>✨ Ingest New Brief / Customize →</span>
                  </button>
                  {onOpenWatermarkModal && (
                    <button
                      type="button"
                      onClick={onOpenWatermarkModal}
                      className="text-xs text-indigo-400 hover:text-indigo-300 font-bold underline cursor-pointer flex items-center gap-1"
                    >
                      <Wand2 className="w-3.5 h-3.5" />
                      <span>Watermark</span>
                    </button>
                  )}
                </div>
              </Card>

              {/* Batch progress strip — makes multi-video runs visible the
                  same way single-video runs are. Hidden when idle. */}
              {batchRun && (
                <div className="animate-fadeIn rounded-3xl border border-indigo-500/40 bg-gradient-to-r from-indigo-950/80 via-slate-900/90 to-slate-900/80 p-5 shadow-xl shadow-indigo-950/30 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="relative flex h-3 w-3 shrink-0">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-60" />
                        <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500" />
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-extrabold text-white flex items-center gap-2 flex-wrap">
                          Batch Processing — Video {Math.min(batchRun.done + 1, batchRun.total)} of {batchRun.total}
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                            <Sparkles className="w-3 h-3" />
                            Sequential — one video at a time
                          </span>
                        </div>
                        {batchRun.currentFile && (
                          <div className="text-xs text-slate-400 truncate max-w-2xl" title={batchRun.currentFile}>
                            {batchRun.currentStatus === "transcribing" && "🎙 Transcribing: "}
                            {batchRun.currentStatus === "strategizing" && "🧠 Extracting strategies: "}
                            {(batchRun.currentStatus === "pending" || batchRun.currentStatus === "downloading") && "⏳ Loading: "}
                            {batchRun.currentFile}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs font-extrabold">
                      <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/25">✓ {batchRun.done} done</span>
                      {batchRun.failed > 0 && (
                        <span className="px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/25">✗ {batchRun.failed} failed</span>
                      )}
                    </div>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all duration-700"
                      style={{ width: `${Math.min(100, Math.round((batchRun.done / Math.max(1, batchRun.total)) * 100))}%` }}
                    />
                  </div>
                </div>
              )}

              {/* System Log Console */}
              <Card className="bg-slate-950 border-slate-800 rounded-2xl p-4 space-y-2 mb-6 shadow-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider">
                    <Activity className="w-3.5 h-3.5 text-indigo-400" /> Live System Console
                  </div>
                </div>
                <div ref={logContainerRef} onScroll={handleLogScroll} className="font-mono text-xs text-slate-300 max-h-40 overflow-y-auto custom-scrollbar space-y-1 bg-slate-950 p-2 rounded-lg">
                  {logs.length === 0 && <span className="text-slate-600 italic">No activity logged yet.</span>}
                  {logs.map((log, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-slate-600 select-none">{String(i + 1).padStart(2, '0')}</span>
                      <span>{log}</span>
                    </div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              </Card>

              {/* Extraction Results Grid & Opus Clip Line Strategy Inspector */}
              {results ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/60 border border-slate-800 p-4 rounded-3xl backdrop-blur-md">
                    <div>
                      <h2 className="text-xl font-extrabold text-white tracking-tight">Extracted Viral Clip Strategies</h2>
                      <p className="text-xs text-slate-400 mt-0.5 flex flex-wrap items-center gap-2">
                        <span>Found <span className="font-bold text-indigo-400">{results.clips?.length || 0} clips</span> using persona: <span className="font-bold text-emerald-400">{results.persona?.type || "General"}</span></span>
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                          <Sparkles className="w-3 h-3 text-indigo-400" />
                          Active Model: {results.active_model || llmLabel}
                        </span>
                        {results.scene_peaks && results.scene_peaks.length > 0 && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                            <span>⛰️</span>
                            {results.scene_peaks.length} scene changes
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      {setSortBy && (
                        <div className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs">
                          <span className="font-bold text-slate-400">Sort by:</span>
                          <select
                            value={sortBy}
                            onChange={(e) => setSortBy(e.target.value as any)}
                            className="font-bold text-white outline-none bg-transparent cursor-pointer"
                          >
                            <option value="score" className="bg-slate-900">Virality Score</option>
                            <option value="energy" className="bg-slate-900">Energy Level</option>
                            <option value="duration" className="bg-slate-900">Duration</option>
                            <option value="hook" className="bg-slate-900">Hook Impact</option>
                          </select>
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={selectedForRender.size === (results.clips?.length || 0) ? deselectAllClips : selectAllClips}
                          className="px-3.5 py-2 rounded-xl bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold transition-all cursor-pointer"
                        >
                          {selectedForRender.size === (results.clips?.length || 0) ? "Deselect All" : "Select All"}
                        </button>
                        {onOpenStylePanel && (
                          <button
                            type="button"
                            onClick={onOpenStylePanel}
                            className="px-3.5 py-2 rounded-xl bg-slate-950 hover:bg-slate-800 text-indigo-400 hover:text-indigo-300 border border-slate-800 text-xs font-extrabold transition-all cursor-pointer flex items-center gap-1.5"
                          >
                            <Settings2 className="w-3.5 h-3.5 text-indigo-400" />
                            Style Panel
                          </button>
                        )}
                        {onToggleLayoutMode && (
                          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800" title="Output format: Full 9:16 vertical (fills screen edge-to-edge) or 1:1 Box (square video with hook banner & bottom captions)">
                            <button
                              type="button"
                              onClick={() => onToggleLayoutMode("portrait")}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${layoutMode === "portrait" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                            >
                              📱 Full 9:16
                            </button>
                            <button
                              type="button"
                              onClick={() => onToggleLayoutMode("box")}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${layoutMode !== "portrait" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                            >
                              1:1 Box
                            </button>
                          </div>
                        )}
                        {onToggleCaptionsBelow && (
                          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800" title="Where captions appear: below the video box (never covers content) or on the video (classic look, covers the lower part)">
                            <button
                              type="button"
                              onClick={() => onToggleCaptionsBelow(true)}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${captionsBelow ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                            >
                              Captions Below
                            </button>
                            <button
                              type="button"
                              onClick={() => onToggleCaptionsBelow(false)}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${captionsBelow ? "text-slate-400 hover:text-white" : "bg-indigo-600 text-white shadow-sm"}`}
                            >
                              On Video
                            </button>
                          </div>
                        )}
                        {onForceHeaderTextChanged && (() => {
                          const activeNarrativeCount = forceHeaderText
                            ? forceHeaderText.split(/\r?\n|\|/).map((s: string) => s.trim()).filter(Boolean).length
                            : 0;
                          const isAutoRotating = activeNarrativeCount > 1;

                          return (
                            <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-xl border border-slate-800" title="Force campaign header narratives. Enter 1 or multiple (separated by | or newlines) to auto-rotate across clips.">
                              <input
                                type="text"
                                list="campaign-header-presets"
                                value={isAutoRotating ? `🎲 [Auto-Rotating ${activeNarrativeCount} Narratives]` : (forceHeaderText || "")}
                                onChange={(e) => onForceHeaderTextChanged(e.target.value)}
                                placeholder="Campaign Header Override (use | to rotate)..."
                                className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-transparent text-white focus:outline-none placeholder:text-slate-500 w-64"
                              />
                              {forceHeaderText && (
                                <button
                                  type="button"
                                  onClick={() => onForceHeaderTextChanged("")}
                                  className="px-1.5 py-1 text-slate-400 hover:text-white text-xs font-bold transition-colors cursor-pointer"
                                  title="Clear forced campaign header"
                                >
                                  ✕
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => {
                                  if (forceHeaderText) {
                                    onForceHeaderTextChanged("");
                                  } else {
                                    const defaultRotation = [
                                      "Wait until you see how this ended... 🤯",
                                      "Nobody expected them to say this out loud 😳",
                                      "The part at the end gave me literal chills 🤯",
                                      "This completely changed my perspective on everything"
                                    ].join("\n");
                                    onForceHeaderTextChanged(defaultRotation);
                                  }
                                }}
                                className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer shrink-0 ${
                                  isAutoRotating
                                    ? "bg-amber-600 text-white shadow-sm"
                                    : forceHeaderText
                                    ? "bg-indigo-600 text-white shadow-sm"
                                    : "bg-slate-900 hover:bg-slate-800 text-indigo-300 border border-slate-800"
                                }`}
                                title={
                                  isAutoRotating
                                    ? `Click to clear ${activeNarrativeCount} active rotating headers`
                                    : forceHeaderText
                                    ? "Click to clear active header"
                                    : "Click to load sample auto-rotating viral headers (or separate your own with |)"
                                }
                              >
                                {isAutoRotating
                                  ? `✓ ${activeNarrativeCount} Rotating`
                                  : forceHeaderText
                                  ? "✓ 1 Active"
                                  : "🎲 Auto-Rotate"}
                              </button>
                              <datalist id="campaign-header-presets">
                                <option value="Wait until you see how this ended... 🤯" />
                                <option value="Nobody expected them to say this out loud 😳" />
                                <option value="The part at the end gave me literal chills 🤯" />
                                <option value="This completely changed my perspective on everything" />
                              </datalist>
                            </div>
                          );
                        })()}
                        {onToggleFaceTrack && (
                          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800" title="Follow the speaker's face horizontally inside the 1:1 box (recommended for wide/interview shots). Off = static centered crop.">
                            <button
                              type="button"
                              onClick={() => onToggleFaceTrack(true)}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${faceTrack ? "bg-rose-600 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}
                            >
                              📍 Face Track On
                            </button>
                            <button
                              type="button"
                              onClick={() => onToggleFaceTrack(false)}
                              className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold transition-all cursor-pointer ${faceTrack ? "text-slate-400 hover:text-white" : "bg-rose-600 text-white shadow-sm"}`}
                            >
                              Off
                            </button>
                          </div>
                        )}
                        <Button
                          variant="gradient"
                          onClick={() => renderAllClips(Array.from(selectedForRender))}
                          disabled={status === "rendering" || status === "strategizing" || selectedForRender.size === 0}
                          className="rounded-xl px-5 py-2 text-xs font-extrabold shadow-lg shadow-indigo-500/20"
                        >
                          <Sparkles className="w-4 h-4 mr-1.5 fill-white" />
                          Render Selected ({selectedForRender.size})
                        </Button>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {(sortedClips || results.clips || []).map((clip: any, rawIdx: number) => {
                      const clipIdx = clip.originalIdx !== undefined ? clip.originalIdx : rawIdx;
                      const isMarked = selectedForRender.has(clipIdx);

                      return (
                      <Card
                        key={clipIdx}
                        className={`transition-all duration-300 rounded-3xl p-5 space-y-4 shadow-xl border ${
                          isMarked
                            ? "bg-slate-900/95 border-indigo-500/40 ring-1 ring-indigo-500/20 shadow-indigo-950/30"
                            : "bg-slate-900/60 border-slate-800/80 opacity-75 hover:opacity-100"
                        }`}
                      >
                        <div className="flex flex-col sm:flex-row items-start gap-4">
                          {(() => {
                            const clipStart = parseFloat(clip.start_time ?? clip.start ?? 0);
                            const rawClipEnd = parseFloat(clip.end_time ?? clip.end ?? 0);
                            const clipEnd = rawClipEnd > clipStart ? rawClipEnd : (clipStart + (parseFloat(clip.duration) || 30));
                            const viralityScoreNum = clip.virality_score != null ? Number(clip.virality_score) : 85;
                            const viralityScoreNorm = viralityScoreNum > 10 ? (viralityScoreNum / 10).toFixed(1) : viralityScoreNum.toFixed(1);

                            return (
                              <>
                                <ClipSegmentPreview clip={clip} clipIdx={clipIdx} API_BASE={API_BASE} />
                                <div className="flex-1 flex flex-col justify-between h-full gap-3 w-full">
                                  <div>
                                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                      <Badge variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/20 font-mono text-[10px] font-extrabold">
                                        🔥 {viralityScoreNorm}/10
                                      </Badge>
                                      <span className="text-[11px] text-slate-400 font-mono">{clipStart.toFixed(0)}s - {clipEnd.toFixed(0)}s</span>
                                      {clip.badge && (
                                        <Badge variant="outline" className="bg-indigo-500/10 text-indigo-300 border-indigo-500/20 text-[10px] font-semibold">
                                          {clip.badge}
                                        </Badge>
                                      )}
                                    </div>
                                    <h3 className="font-extrabold text-sm text-white line-clamp-2">{clip.title || `Clip #${clipIdx + 1}`}</h3>
                                  </div>

                                  <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-800/60">
                                    <button
                                      type="button"
                                      onClick={() => toggleSelectClip(clipIdx)}
                                      className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-extrabold border transition-all cursor-pointer ${
                                        isMarked
                                          ? "bg-indigo-500/20 border-indigo-500/50 text-indigo-200 shadow-sm"
                                          : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
                                      }`}
                                    >
                                      <div className={`w-4 h-4 rounded-md flex items-center justify-center border transition-all ${
                                        isMarked
                                          ? "bg-indigo-600 border-indigo-500 text-white"
                                          : "border-slate-700 bg-slate-900"
                                      }`}>
                                        {isMarked && <CheckCircle2 className="w-3.5 h-3.5" />}
                                      </div>
                                      <span>{isMarked ? "Marked for Render" : "Mark for Render"}</span>
                                    </button>

                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => renderClip(clipIdx)}
                                      disabled={status === "rendering"}
                                      className="rounded-xl text-xs font-bold text-slate-400 hover:text-white hover:bg-slate-800"
                                      title="Render only this clip immediately"
                                    >
                                      <Zap className="w-3.5 h-3.5 mr-1 text-amber-400" /> Render Solo
                                    </Button>
                                  </div>
                                </div>
                              </>
                            );
                          })()}
                        </div>

                        <p className="text-xs text-slate-300 italic border-l-2 border-indigo-500 pl-3 py-0.5 bg-slate-950/40 rounded-r-lg">
                          "{clip.hook_sentence || clip.reasoning || "High viral engagement moment"}"
                        </p>

                        {/* Opus Clip Line Inspector */}
                        {(() => {
                          const clipStart = parseFloat(clip.start_time ?? clip.start ?? 0);
                          const rawClipEnd = parseFloat(clip.end_time ?? clip.end ?? 0);
                          const clipEnd = rawClipEnd > clipStart ? rawClipEnd : (clipStart + (parseFloat(clip.duration) || 30));
                          const viralityScoreNum = clip.virality_score != null ? Number(clip.virality_score) : 85;
                          const viralityScoreNorm = viralityScoreNum > 10 ? viralityScoreNum / 10 : viralityScoreNum;

                          return (
                            <LineStrategyInspector
                              clipTitle={clip.title || `Clip #${clipIdx + 1}`}
                              clipStart={clipStart}
                              clipEnd={clipEnd}
                              viralityScore={viralityScoreNorm}
                              explanation={clip.reasoning || clip.explanation || clip.virality_reason}
                              wordTimestamps={clip.word_timestamps || []}
                            />
                          );
                        })()}
                      </Card>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <Card className="border-dashed border-slate-800/80 bg-slate-900/40 p-12 text-center rounded-3xl backdrop-blur-xl">
                  <Scissors className="w-12 h-12 text-indigo-400 opacity-30 mx-auto mb-3" />
                  <h3 className="text-base font-extrabold text-slate-200">Ready for a Video URL or Local MP4 File</h3>
                  <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">Paste a URL above or drop a video into your local watch folder to start extracting viral clips.</p>
                </Card>
              )}


            </div>
          )}

          {/* TAB 2: RENDER GALLERY */}
          {activeView === "gallery" && (
            <div className="max-w-6xl mx-auto space-y-6 animate-fadeIn">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-4">
                  <h2 className="text-xl font-extrabold text-white tracking-tight">Rendered Gallery</h2>
                  {setGalleryFilter && (
                    <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 p-1 rounded-xl text-xs font-bold">
                      {[
                        { id: "all", label: "All Clips" },
                        { id: "today", label: "Today" },
                        { id: "over30", label: "≥ 30s" },
                        { id: "under30", label: "< 30s" },
                      ].map((f) => (
                        <button
                          key={f.id}
                          onClick={() => setGalleryFilter(f.id as any)}
                          className={`px-2.5 py-1 rounded-lg transition-all ${
                            galleryFilter === f.id
                              ? "bg-indigo-600 text-white shadow-md"
                              : "text-slate-400 hover:text-white"
                          }`}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <div className="relative min-w-[200px]">
                    <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-2.5" />
                    <input
                      type="text"
                      placeholder="Search title, topic, keyword..."
                      value={gallerySearch}
                      onChange={(e) => setGallerySearch(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-indigo-500 transition-all font-medium"
                    />
                  </div>

                  <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs">
                    <span className="font-bold text-slate-400">Group By:</span>
                    <select
                      value={galleryGroupBy}
                      onChange={(e) => setGalleryGroupBy(e.target.value as any)}
                      className="font-bold text-white outline-none bg-transparent cursor-pointer"
                    >
                      <option value="none" className="bg-slate-900">None (Grid)</option>
                      <option value="video" className="bg-slate-900">By Video / Session</option>
                      <option value="topic" className="bg-slate-900">By Topic</option>
                    </select>
                  </div>

                  {status === "rendering" && onCancelProcess && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={onCancelProcess}
                      className="rounded-xl font-bold shadow-lg shadow-rose-500/20"
                    >
                      <Square className="w-3.5 h-3.5 mr-1.5 fill-white" />
                      Stop Render
                    </Button>
                  )}

                  {onOpenOutputDir && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onOpenOutputDir()}
                      className="rounded-xl border-slate-800 text-xs font-bold text-slate-300 hover:text-white"
                    >
                      <Folder className="w-3.5 h-3.5 text-indigo-400 mr-1.5" />
                      Open Render Directory
                    </Button>
                  )}
                  <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs">
                    <span className="font-bold text-slate-400">Session:</span>
                    <select
                      value={gallerySessionMode}
                      onChange={(e) => setGallerySessionMode(e.target.value as any)}
                      className="font-bold text-white outline-none bg-transparent cursor-pointer"
                    >
                      <option value="current" className="bg-slate-900">Current Session Only</option>
                      <option value="all" className="bg-slate-900">All Saved Sessions</option>
                    </select>
                  </div>
                </div>
              </div>

              {searchedGallery.length === 0 ? (
                <Card className="border-dashed border-slate-800 bg-slate-900/40 p-12 text-center rounded-3xl">
                  <Film className="w-12 h-12 text-purple-400 opacity-30 mx-auto mb-3" />
                  <h3 className="text-base font-extrabold text-slate-200">No Rendered Clips Found</h3>
                  <p className="text-xs text-slate-500 mt-1">Render clips from the Extraction Studio or clear search filters to populate your gallery.</p>
                </Card>
              ) : galleryGroupBy !== "none" ? (
                <div className="space-y-6">
                  {Object.entries(
                    searchedGallery.reduce((acc: Record<string, any[]>, item: any) => {
                      const key = galleryGroupBy === "video"
                        ? (item.video_id || item.session_id || "Current Video Session")
                        : (item.topic || "General Highlights");
                      if (!acc[key]) acc[key] = [];
                      acc[key].push(item);
                      return acc;
                    }, {})
                  ).map(([groupKey, groupItems]) => (
                    <div key={groupKey} className="space-y-3">
                      <div className="flex items-center justify-between gap-3 pt-2 border-b border-slate-800 pb-2">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-extrabold text-indigo-400">
                            {galleryGroupBy === "video" ? "🎬 Video / Session:" : "🏷️ Topic:"} {groupKey}
                          </span>
                          <Badge variant="outline" className="bg-indigo-500/10 text-indigo-300 border-indigo-500/20 text-[10px] font-bold">
                            {groupItems.length} {groupItems.length === 1 ? "clip" : "clips"}
                          </Badge>
                        </div>
                        {onOpenOutputDir && galleryGroupBy === "video" && (
                          <button
                            type="button"
                            onClick={() => onOpenOutputDir(groupKey)}
                            title="Open this session's folder in File Explorer"
                            className="text-xs text-slate-400 hover:text-indigo-400 flex items-center gap-1 font-bold transition-colors"
                          >
                            <Folder className="w-3.5 h-3.5" />
                            <span>Open Folder</span>
                          </button>
                        )}
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                        {groupItems.map((item, i) => (
                          <Card key={i} className="bg-slate-900/90 border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col group hover:border-indigo-500/30 transition-all">
                            <div className="aspect-[9/16] bg-slate-950 relative overflow-hidden">
                              <video src={item.url} controls className="w-full h-full object-cover" />
                            </div>
                            <div className="p-3.5 space-y-2 flex-1 flex flex-col justify-between">
                              <div className="flex items-center justify-between gap-1">
                                <h4 className="font-bold text-xs text-white truncate" title={item.filename}>{item.filename}</h4>
                                {onOpenOutputDir && (
                                  <button
                                    type="button"
                                    onClick={() => onOpenOutputDir(item.video_id || item.session_id)}
                                    title="Open folder in File Explorer"
                                    className="text-slate-500 hover:text-indigo-400 transition-colors p-1"
                                  >
                                    <Folder className="w-3.5 h-3.5" />
                                  </button>
                                )}
                              </div>
                              <div className="flex items-center gap-1.5 pt-2 border-t border-slate-800/80">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => openEditor("trim", item)}
                                  className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                                >
                                  <Scissors className="w-3 h-3 mr-1 text-indigo-400" /> Trim
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => openEditor("watermark", item)}
                                  className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                                >
                                  <Wand2 className="w-3 h-3 mr-1 text-purple-400" /> Logo
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => openEditor("crop", item)}
                                  className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                                >
                                  <Crop className="w-3 h-3 mr-1 text-emerald-400" /> Crop
                                </Button>
                              </div>
                            </div>
                          </Card>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                  {searchedGallery.map((item, i) => (
                    <Card key={i} className="bg-slate-900/90 border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col group hover:border-indigo-500/30 transition-all">
                      <div className="aspect-[9/16] bg-slate-950 relative overflow-hidden">
                        <video src={item.url} controls className="w-full h-full object-cover" />
                      </div>
                      <div className="p-3.5 space-y-2 flex-1 flex flex-col justify-between">
                        <div className="flex items-center justify-between gap-1">
                          <h4 className="font-bold text-xs text-white truncate" title={item.filename}>{item.filename}</h4>
                          {onOpenOutputDir && (
                            <button
                              type="button"
                              onClick={() => onOpenOutputDir(item.video_id || item.session_id)}
                              title="Open folder in File Explorer"
                              className="text-slate-500 hover:text-indigo-400 transition-colors p-1"
                            >
                              <Folder className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 pt-2 border-t border-slate-800/80">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditor("trim", item)}
                            className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                          >
                            <Scissors className="w-3 h-3 mr-1 text-indigo-400" /> Trim
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditor("watermark", item)}
                            className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                          >
                            <Wand2 className="w-3 h-3 mr-1 text-purple-400" /> Logo
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditor("crop", item)}
                            className="h-7 text-[10px] px-2 border-slate-800 text-slate-300 hover:text-white"
                          >
                            <Crop className="w-3 h-3 mr-1 text-emerald-400" /> Crop
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: WHOP PAYOUT STUDIO */}
          {activeView === "whop" && (
            <div className="max-w-6xl mx-auto animate-fadeIn">
              <WhopPublisher campaignSlug={selectedCampaignId || "default"} clips={results?.clips || []} activeProfile={activeProfile} onExportPackage={onExportPackage} />
            </div>
          )}

          {/* TAB 4: STORAGE MANAGER */}
          {activeView === "storage" && (
            <StorageManager API_BASE={API_BASE} addLog={addLog} />
          )}
        </main>
      </div>

      {showPurgeModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4">
          <Card className="max-w-md w-full bg-slate-900 border-rose-500/40 rounded-3xl p-6 shadow-2xl space-y-5 animate-scaleIn">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-rose-500/20 border border-rose-500/30 flex items-center justify-center text-rose-400">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-extrabold text-base text-white">Purge Session & Reset App?</h3>
                <p className="text-xs text-rose-400 font-medium">This action is permanent and cannot be undone.</p>
              </div>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Are you sure you want to completely delete all temporary working files, transcript caches, and rendered video clips associated with this session from disk?
            </p>
            <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-800">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowPurgeModal?.(false)}
                className="rounded-xl border-slate-700 text-slate-300 hover:text-white"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={confirmPurge}
                className="rounded-xl bg-gradient-to-r from-rose-600 to-red-600 text-white font-extrabold shadow-lg"
              >
                Confirm Purge & Reset
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
