"use client";

import { useState } from "react";
import { Settings2, X, Check, Grid, Sliders, ToggleLeft, Layers } from "lucide-react";
import { Button } from "./ui/button";

export const HEADER_OPTIONS = ["italic-serif", "rounded-chunky", "bold-caps-yellow", "minimal-clean", "dark-pill", "cyber-pill", "luxury-gold"];
export const TITLE_OPTIONS = ["Impact", "Box", "Yellow", "Neon", "Orange", "Suits", "Meme", "ViralItalic"];
export const CAPTION_OPTIONS = ["Classic", "Outline", "Minimal", "Minimalist", "Fire", "Hormozi", "MrBeast", "OpusCyber", "VoxDoc", "LuxuryGold", "AliAbdaal", "PodcastPop", "CinematicSlate", "NeonGlow"];
export const HOOK_OPTIONS = ["BlackOnWhiteBox", "YellowOnBlackBox", "BoldWhite", "BrightYellow", "Suits", "Meme", "None"];

interface StylePanelModalProps {
  isOpen: boolean;
  onClose: () => void;
  styleMode: "random" | "fixed";
  styleAllowlist: Record<string, string[]>;
  fixedStyle: Record<string, string>;
  onSave: (mode: "random" | "fixed", allowlist: Record<string, string[]>, fixed: Record<string, string>) => void;
}

export function StylePanelModal({
  isOpen,
  onClose,
  styleMode,
  styleAllowlist,
  fixedStyle,
  onSave
}: StylePanelModalProps) {
  const [localMode, setLocalMode] = useState<"random" | "fixed">(styleMode);
  
  const [localAllowlist, setLocalAllowlist] = useState<Record<string, string[]>>(() => {
    return {
      header: styleAllowlist.header && styleAllowlist.header.length > 0 ? styleAllowlist.header.filter(h => HEADER_OPTIONS.includes(h)) : [...HEADER_OPTIONS],
      title: styleAllowlist.title && styleAllowlist.title.length > 0 ? styleAllowlist.title : [...TITLE_OPTIONS],
      caption: styleAllowlist.caption && styleAllowlist.caption.length > 0 ? styleAllowlist.caption : [...CAPTION_OPTIONS],
      hook: styleAllowlist.hook && styleAllowlist.hook.length > 0 ? styleAllowlist.hook : [...HOOK_OPTIONS],
    };
  });

  const [localFixed, setLocalFixed] = useState<Record<string, string>>(() => {
    return {
      header: fixedStyle.header || "rounded-chunky",
      title: fixedStyle.title || "Impact",
      caption: fixedStyle.caption || "Hormozi",
      hook: fixedStyle.hook || "BlackOnWhiteBox",
    };
  });

  if (!isOpen) return null;

  const handleToggleAllowlist = (category: string, item: string) => {
    setLocalAllowlist(prev => {
      const current = prev[category] || [];
      const updated = current.includes(item)
        ? current.filter(x => x !== item)
        : [...current, item];
      return { ...prev, [category]: updated };
    });
  };

  const handleSelectAllCategory = (category: string, options: string[]) => {
    setLocalAllowlist(prev => ({
      ...prev,
      [category]: [...options]
    }));
  };

  const handleDeselectAllCategory = (category: string) => {
    setLocalAllowlist(prev => ({
      ...prev,
      [category]: []
    }));
  };

  const handleSave = () => {
    const finalAllowlist = {
      header: localAllowlist.header.length > 0 ? localAllowlist.header : [...HEADER_OPTIONS],
      title: localAllowlist.title.length > 0 ? localAllowlist.title : [...TITLE_OPTIONS],
      caption: localAllowlist.caption.length > 0 ? localAllowlist.caption : [...CAPTION_OPTIONS],
      hook: localAllowlist.hook.length > 0 ? localAllowlist.hook : [...HOOK_OPTIONS],
    };
    onSave(localMode, finalAllowlist, localFixed);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-[250] flex items-center justify-center p-4" onClick={onClose}>
      <div 
        className="bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl w-[680px] max-w-[95vw] max-h-[85vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
          <h3 className="text-base font-extrabold text-white flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-indigo-400" />
            Style Selection Panel
          </h3>
          <button 
            onClick={onClose} 
            className="text-slate-400 hover:text-white hover:bg-slate-800 p-1.5 rounded-xl transition-all cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Mode Selector Toggle */}
        <div className="p-4 border-b border-slate-800/80 bg-slate-950/20 flex flex-wrap gap-4 items-center justify-between">
          <div className="space-y-0.5">
            <span className="text-xs font-bold text-slate-300">Style Generator Mode</span>
            <p className="text-[10px] text-slate-500">Choose between randomized styling or single fixed preset overlays.</p>
          </div>
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              type="button"
              onClick={() => setLocalMode("random")}
              className={`px-3 py-1.5 rounded-lg text-xs font-extrabold transition-all cursor-pointer flex items-center gap-1.5 ${
                localMode === "random"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-500/20"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <Grid className="w-3.5 h-3.5" />
              Randomize Preset
            </button>
            <button
              type="button"
              onClick={() => setLocalMode("fixed")}
              className={`px-3 py-1.5 rounded-lg text-xs font-extrabold transition-all cursor-pointer flex items-center gap-1.5 ${
                localMode === "fixed"
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-500/20"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <Sliders className="w-3.5 h-3.5" />
              Fixed Style
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 p-6 overflow-y-auto custom-scrollbar space-y-6">
          {localMode === "random" ? (
            <div className="space-y-6">
              <div className="bg-indigo-950/20 text-indigo-300 p-3 rounded-xl border border-indigo-950 text-[10px] leading-relaxed">
                💡 **Randomized Mode**: Check/uncheck presets below. The rendering engine will only select from the checked styles for each clip.
              </div>

              {/* Header Allowlist */}
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span className="text-xs font-extrabold text-slate-300 uppercase tracking-wider">Allowed Header Styles</span>
                  <div className="flex gap-2">
                    <button 
                      type="button" 
                      onClick={() => handleSelectAllCategory("header", HEADER_OPTIONS)}
                      className="text-[10px] font-bold text-indigo-400 hover:underline"
                    >
                      Select All
                    </button>
                    <span className="text-slate-700 text-[10px]">•</span>
                    <button 
                      type="button" 
                      onClick={() => handleDeselectAllCategory("header")}
                      className="text-[10px] font-bold text-slate-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {HEADER_OPTIONS.map(h => {
                    const checked = (localAllowlist.header || []).includes(h);
                    return (
                      <label 
                        key={h} 
                        className={`flex items-center gap-2 p-2 rounded-xl border text-xs font-semibold cursor-pointer select-none transition-all ${
                          checked 
                            ? "bg-indigo-600/10 border-indigo-500/40 text-indigo-300" 
                            : "bg-slate-950 border-slate-900 text-slate-400 hover:text-white hover:border-slate-800"
                        }`}
                      >
                        <input 
                          type="checkbox" 
                          checked={checked}
                          onChange={() => handleToggleAllowlist("header", h)}
                          className="rounded text-indigo-600 accent-indigo-600 focus:ring-0" 
                        />
                        <span className="truncate">{h}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Title Allowlist */}
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span className="text-xs font-extrabold text-slate-300 uppercase tracking-wider">Allowed Title Styles</span>
                  <div className="flex gap-2">
                    <button 
                      type="button" 
                      onClick={() => handleSelectAllCategory("title", TITLE_OPTIONS)}
                      className="text-[10px] font-bold text-indigo-400 hover:underline"
                    >
                      Select All
                    </button>
                    <span className="text-slate-700 text-[10px]">•</span>
                    <button 
                      type="button" 
                      onClick={() => handleDeselectAllCategory("title")}
                      className="text-[10px] font-bold text-slate-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {TITLE_OPTIONS.map(t => {
                    const checked = (localAllowlist.title || []).includes(t);
                    return (
                      <label 
                        key={t} 
                        className={`flex items-center gap-2 p-2 rounded-xl border text-xs font-semibold cursor-pointer select-none transition-all ${
                          checked 
                            ? "bg-indigo-600/10 border-indigo-500/40 text-indigo-300" 
                            : "bg-slate-950 border-slate-900 text-slate-400 hover:text-white hover:border-slate-800"
                        }`}
                      >
                        <input 
                          type="checkbox" 
                          checked={checked}
                          onChange={() => handleToggleAllowlist("title", t)}
                          className="rounded text-indigo-600 accent-indigo-600 focus:ring-0" 
                        />
                        <span className="truncate">{t}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Caption Allowlist */}
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span className="text-xs font-extrabold text-slate-300 uppercase tracking-wider">Allowed Caption Styles</span>
                  <div className="flex gap-2">
                    <button 
                      type="button" 
                      onClick={() => handleSelectAllCategory("caption", CAPTION_OPTIONS)}
                      className="text-[10px] font-bold text-indigo-400 hover:underline"
                    >
                      Select All
                    </button>
                    <span className="text-slate-700 text-[10px]">•</span>
                    <button 
                      type="button" 
                      onClick={() => handleDeselectAllCategory("caption")}
                      className="text-[10px] font-bold text-slate-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {CAPTION_OPTIONS.map(c => {
                    const checked = (localAllowlist.caption || []).includes(c);
                    return (
                      <label 
                        key={c} 
                        className={`flex items-center gap-2 p-2 rounded-xl border text-xs font-semibold cursor-pointer select-none transition-all ${
                          checked 
                            ? "bg-indigo-600/10 border-indigo-500/40 text-indigo-300" 
                            : "bg-slate-950 border-slate-900 text-slate-400 hover:text-white hover:border-slate-800"
                        }`}
                      >
                        <input 
                          type="checkbox" 
                          checked={checked}
                          onChange={() => handleToggleAllowlist("caption", c)}
                          className="rounded text-indigo-600 accent-indigo-600 focus:ring-0" 
                        />
                        <span className="truncate">{c}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Hook Allowlist */}
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span className="text-xs font-extrabold text-slate-300 uppercase tracking-wider">Allowed Hook Styles</span>
                  <div className="flex gap-2">
                    <button 
                      type="button" 
                      onClick={() => handleSelectAllCategory("hook", HOOK_OPTIONS)}
                      className="text-[10px] font-bold text-indigo-400 hover:underline"
                    >
                      Select All
                    </button>
                    <span className="text-slate-700 text-[10px]">•</span>
                    <button 
                      type="button" 
                      onClick={() => handleDeselectAllCategory("hook")}
                      className="text-[10px] font-bold text-slate-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {HOOK_OPTIONS.map(h => {
                    const checked = (localAllowlist.hook || []).includes(h);
                    return (
                      <label 
                        key={h} 
                        className={`flex items-center gap-2 p-2 rounded-xl border text-xs font-semibold cursor-pointer select-none transition-all ${
                          checked 
                            ? "bg-indigo-600/10 border-indigo-500/40 text-indigo-300" 
                            : "bg-slate-950 border-slate-900 text-slate-400 hover:text-white hover:border-slate-800"
                        }`}
                      >
                        <input 
                          type="checkbox" 
                          checked={checked}
                          onChange={() => handleToggleAllowlist("hook", h)}
                          className="rounded text-indigo-600 accent-indigo-600 focus:ring-0" 
                        />
                        <span className="truncate">{h}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-emerald-950/20 text-emerald-300 p-3 rounded-xl border border-emerald-950 text-[10px] leading-relaxed">
                💡 **Fixed Mode**: Specify a single fixed style preset to apply uniformly across all clips.
              </div>

              {/* Fixed Header Style */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fixed Header Style</label>
                <select
                  value={localFixed.header}
                  onChange={(e) => setLocalFixed(prev => ({ ...prev, header: e.target.value }))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                >
                  {HEADER_OPTIONS.map(h => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </div>

              {/* Fixed Title Style */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fixed Title Style</label>
                <select
                  value={localFixed.title}
                  onChange={(e) => setLocalFixed(prev => ({ ...prev, title: e.target.value }))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                >
                  {TITLE_OPTIONS.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>

              {/* Fixed Caption Style */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fixed Caption Style</label>
                <select
                  value={localFixed.caption}
                  onChange={(e) => setLocalFixed(prev => ({ ...prev, caption: e.target.value }))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                >
                  {CAPTION_OPTIONS.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              {/* Fixed Hook Style */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fixed Hook Style</label>
                <select
                  value={localFixed.hook}
                  onChange={(e) => setLocalFixed(prev => ({ ...prev, hook: e.target.value }))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-semibold outline-none cursor-pointer focus:border-indigo-500"
                >
                  {HOOK_OPTIONS.map(h => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/60 flex justify-end gap-3">
          <button 
            onClick={onClose} 
            className="px-5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-extrabold rounded-xl text-xs transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <Button 
            variant="gradient"
            onClick={handleSave} 
            className="px-5 py-2 text-xs font-extrabold cursor-pointer"
          >
            Save Style Settings
          </Button>
        </div>
      </div>
    </div>
  );
}
