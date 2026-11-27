"use client";

import { Folder, Play, Square, Server, Zap, Sparkles, Film, Activity } from "lucide-react";

interface HeaderProps {
  apiStatus: "connected" | "disconnected" | "checking";
  watchDir: string;
  queueState: {
    queue: any[];
    queue_running: boolean;
    queue_active_item?: any;
    queue_watch_dir: string;
    clips_by_video?: Record<string, number[]>;
  } | null;
  extractedCount?: number;
  galleryCount?: number;
  activeCampaignName?: string;
  onOpenCampaignModal?: () => void;
  onPickFolder: () => void;
  onStartQueue: () => void;
  onStopQueue: () => void;
  onResetSession?: () => void;
  llmLabel?: string;
  setLlmLabel?: (v: string) => void;
  llmCatalog?: any[];
}

export function Header({
  apiStatus,
  watchDir,
  queueState,
  extractedCount = 0,
  galleryCount = 0,
  activeCampaignName = "David Heacock",
  onOpenCampaignModal,
  onPickFolder,
  onStartQueue,
  onStopQueue,
  onResetSession,
  llmLabel = "",
  setLlmLabel,
  llmCatalog = [],
}: HeaderProps) {
  const isQueueActive = queueState?.queue_running || false;
  const pendingCount = queueState?.queue?.filter((i: any) => i.status === "pending" || i.status === "downloading" || i.status === "transcribing" || i.status === "strategizing").length || 0;

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl">
      <div className="w-full px-6 h-16 flex items-center justify-between gap-4">
        {/* Top Studio Metrics Bar */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenCampaignModal}
              className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-indigo-950 to-purple-950/60 hover:from-indigo-900 hover:to-purple-900/80 border border-indigo-500/30 text-xs font-extrabold text-white flex items-center gap-2 shadow-lg transition-all cursor-pointer group"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-300">Campaign:</span>
              <span className="text-indigo-300 font-extrabold group-hover:text-white transition-colors">{activeCampaignName}</span>
            </button>
          </div>
          
          {llmCatalog && llmCatalog.length > 0 && setLlmLabel && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-300">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-slate-400 font-medium hidden sm:inline">Model:</span>
              <select
                value={llmLabel}
                onChange={(e) => setLlmLabel(e.target.value)}
                className="bg-transparent border-none text-indigo-300 font-extrabold outline-none cursor-pointer text-xs max-w-[180px] focus:text-white transition-colors"
              >
                {llmCatalog.map((m: any) => (
                  <option key={m.label} value={m.label} className="bg-slate-950 text-white font-medium">
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="hidden lg:flex items-center gap-2 border-l border-slate-800 pl-3">
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-300">
              <Film className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-slate-400 font-medium">Extracted:</span>
              <span className="font-extrabold text-white font-mono">{extractedCount}</span>
            </div>

            <div className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-300">
              <Zap className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-400 font-medium">Gallery:</span>
              <span className="font-extrabold text-white font-mono">{galleryCount}</span>
            </div>
          </div>
        </div>

        {/* Action Controls & Status Pills */}
        <div className="flex items-center gap-3">
          {/* FastAPI Local Engine Indicator */}
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs font-semibold text-slate-300">
            <span
              className={`h-2 w-2 rounded-full ${
                apiStatus === "connected"
                  ? "bg-emerald-400 animate-pulse"
                  : apiStatus === "checking"
                  ? "bg-amber-400"
                  : "bg-rose-500"
              }`}
            />
            <Server className="h-3.5 w-3.5 text-indigo-400" />
            <span className="text-slate-300 font-mono text-[11px]">FastAPI Local</span>
          </div>

          {/* Folder Watcher Controls */}
          <div className="flex items-center gap-2 bg-slate-900/90 p-1 rounded-xl border border-slate-800">
            <button
              onClick={onPickFolder}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-slate-300 hover:bg-slate-800 transition-all cursor-pointer"
              title={watchDir ? `Batch folder: ${watchDir}` : "Select batch folder to process videos automatically"}
            >
              <Folder className="h-3.5 w-3.5 text-indigo-400" />
              <span className="max-w-[140px] truncate hidden md:inline">
                {watchDir ? watchDir.split(/[\\/]/).pop() : "Add Batch Folder"}
              </span>
            </button>

            {queueState && (pendingCount > 0 || isQueueActive) && (
              <button
                onClick={isQueueActive ? onStopQueue : onStartQueue}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  isQueueActive
                    ? "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                    : "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                }`}
              >
                {isQueueActive ? (
                  <>
                    <Square className="h-3 w-3 fill-current" />
                    <span>Stop Queue ({pendingCount})</span>
                  </>
                ) : (
                  <>
                    <Play className="h-3 w-3 fill-current" />
                    <span>Run Queue ({pendingCount})</span>
                  </>
                )}
              </button>
            )}

            {onResetSession && (
              <button
                onClick={onResetSession}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/25 transition-all cursor-pointer"
                title="Reset session state and clear cache"
              >
                <Square className="h-3 w-3 text-indigo-400" />
                <span>Reset App</span>
              </button>
            )}
          </div>

          {/* Dark Mode Toggle Removed */}
        </div>
      </div>
    </header>
  );
}
