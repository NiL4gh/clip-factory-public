"use client";

import { useState } from "react";
import { Zap, Film, DollarSign, Settings2, Folder, ChevronLeft, ChevronRight, Server, Sparkles, Activity, HardDrive } from "lucide-react";
import { Badge } from "./badge";
import { Button } from "./button";

interface SidebarProps {
  activeView: "workspace" | "gallery" | "whop" | "storage";
  onSelectView: (view: "workspace" | "gallery" | "whop" | "storage") => void;
  onOpenSettings: () => void;
  galleryCount: number;
  apiStatus: "connected" | "disconnected" | "checking";
  watchDir: string;
  onPickFolder: () => void;
}

export function Sidebar({
  activeView,
  onSelectView,
  onOpenSettings,
  galleryCount,
  apiStatus,
  watchDir,
  onPickFolder,
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`relative flex flex-col h-full bg-slate-950/90 border-r border-slate-800/80 backdrop-blur-xl transition-all duration-300 z-30 select-none ${
        collapsed ? "w-20" : "w-64"
      }`}
    >
      {/* Collapse Toggle Button */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-6 h-7 w-7 rounded-full bg-slate-900 border border-slate-700 text-slate-400 hover:text-white flex items-center justify-center shadow-md cursor-pointer z-40 transition-transform hover:scale-105"
        title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>

      {/* App Branding & Header */}
      <div className="p-4 border-b border-slate-800/80 flex items-center gap-3">
        <div className="h-10 w-10 shrink-0 rounded-2xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-pink-500 flex items-center justify-center shadow-lg shadow-indigo-500/25 ring-1 ring-white/20">
          <Zap className="h-5 w-5 text-white" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <div className="flex items-center gap-1.5">
              <h1 className="font-extrabold text-base tracking-tight text-white font-jakarta truncate">
                ClipFactory<span className="gradient-text">.ai</span>
              </h1>
            </div>
            <p className="text-[10px] text-slate-400 font-semibold tracking-wider uppercase truncate">
              Local AI Clipper
            </p>
          </div>
        )}
      </div>

      {/* Navigation Item Links */}
      <div className="flex-1 p-3 space-y-1.5 overflow-y-auto custom-scrollbar">
        <button
          onClick={() => onSelectView("workspace")}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-2xl text-xs font-extrabold transition-all cursor-pointer ${
            activeView === "workspace"
              ? "bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25 glow-indigo"
              : "text-slate-400 hover:text-white hover:bg-slate-900"
          }`}
          title="Extraction Workspace"
        >
          <Zap className="h-4 w-4 shrink-0 text-indigo-400" />
          {!collapsed && <span className="truncate">Extraction Studio</span>}
        </button>

        <button
          onClick={() => onSelectView("gallery")}
          className={`w-full flex items-center justify-between px-3 py-3 rounded-2xl text-xs font-extrabold transition-all cursor-pointer ${
            activeView === "gallery"
              ? "bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25 glow-indigo"
              : "text-slate-400 hover:text-white hover:bg-slate-900"
          }`}
          title="Rendered Gallery"
        >
          <div className="flex items-center gap-3">
            <Film className="h-4 w-4 shrink-0 text-purple-400" />
            {!collapsed && <span className="truncate">Render Gallery</span>}
          </div>
          {!collapsed && (
            <Badge variant="outline" className="px-2 py-0.5 text-[9px] bg-slate-900 border-slate-800 text-purple-400">
              {galleryCount}
            </Badge>
          )}
        </button>

        <button
          onClick={() => onSelectView("whop")}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-2xl text-xs font-extrabold transition-all cursor-pointer ${
            activeView === "whop"
              ? "bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-lg shadow-emerald-500/25 glow-emerald"
              : "text-slate-400 hover:text-white hover:bg-slate-900"
          }`}
          title="Whop Content Rewards Studio"
        >
          <DollarSign className="h-4 w-4 shrink-0 text-emerald-400" />
          {!collapsed && <span className="truncate">Whop Payout Studio</span>}
        </button>

        <button
          onClick={() => onSelectView("storage")}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-2xl text-xs font-extrabold transition-all cursor-pointer ${
            activeView === "storage"
              ? "bg-gradient-to-r from-sky-600 to-cyan-600 text-white shadow-lg shadow-sky-500/25 glow-sky"
              : "text-slate-400 hover:text-white hover:bg-slate-900"
          }`}
          title="Storage Manager"
        >
          <HardDrive className="h-4 w-4 shrink-0 text-sky-400" />
          {!collapsed && <span className="truncate">Storage Manager</span>}
        </button>
      </div>

      {/* Footer Info & Folder Watcher */}
      <div className="p-3 border-t border-slate-800/80 space-y-2">
        <button
          onClick={onPickFolder}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-bold text-slate-300 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 transition-all cursor-pointer"
          title={watchDir ? `Batch folder: ${watchDir}` : "Select batch folder to process videos automatically"}
        >
          <Folder className="h-4 w-4 text-indigo-400 shrink-0" />
          {!collapsed && (
            <span className="truncate text-[11px]">
              {watchDir ? watchDir.split(/[\\/]/).pop() : "Add Batch Folder"}
            </span>
          )}
        </button>

        <button
          onClick={onOpenSettings}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-bold text-slate-400 hover:text-white bg-transparent hover:bg-slate-900 transition-all cursor-pointer"
          title="Settings & Storage"
        >
          <Settings2 className="h-4 w-4 shrink-0 text-slate-400" />
          {!collapsed && <span className="truncate text-[11px]">Studio Settings</span>}
        </button>

        {!collapsed && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/60 border border-slate-800/60 text-[10px] text-slate-400 font-mono">
            <span
              className={`h-2 w-2 rounded-full ${
                apiStatus === "connected"
                  ? "bg-emerald-400 animate-pulse"
                  : "bg-rose-500"
              }`}
            />
            <span className="truncate">FastAPI Local Engine</span>
          </div>
        )}
      </div>
    </aside>
  );
}
