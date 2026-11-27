"use client";

import { useState } from "react";
import { Sparkles, Check, Folder, RefreshCw, Layers, Sliders, Hash, Clock, X, Zap } from "lucide-react";
import axios from "axios";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Button } from "../ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "../ui/card";
import { Badge } from "../ui/badge";

interface CampaignModalProps {
  isOpen: boolean;
  onClose: () => void;
  campaigns: { id: string; name: string; brief: string }[];
  activeCampaignId: string;
  activeProfile: any;
  onSelectCampaign: (id: string) => Promise<void>;
  onCampaignCreated: () => Promise<void>;
  API_BASE: string;
}

export function CampaignModal({
  isOpen,
  onClose,
  campaigns,
  activeCampaignId,
  activeProfile,
  onSelectCampaign,
  onCampaignCreated,
  API_BASE,
}: CampaignModalProps) {
  const [tab, setTab] = useState<"switch" | "ingest">("switch");
  const [rawBrief, setRawBrief] = useState("");
  const [campaignName, setCampaignName] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzedResult, setAnalyzedResult] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const handleAnalyze = async () => {
    if (!rawBrief.trim()) {
      setErrorMsg("Please paste or upload a raw campaign brief.");
      return;
    }
    setErrorMsg("");
    setIsAnalyzing(true);
    try {
      const res = await axios.post(`${API_BASE}/campaigns/analyze`, {
        raw_brief: rawBrief,
        name: campaignName.trim() || undefined,
      });
      if (res.data?.profile) {
        setAnalyzedResult(res.data.profile);
        await onCampaignCreated();
      }
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || "Failed to analyze campaign brief.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const content = evt.target?.result as string;
      if (content) {
        setRawBrief(content);
        if (!campaignName) {
          setCampaignName(file.name.replace(/\.[^/.]+$/, "").replace(/[-_]/g, " "));
        }
      }
    };
    reader.readAsText(file);
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl bg-slate-900 border-slate-800 text-slate-100 p-6 rounded-3xl space-y-6 shadow-2xl">
        <DialogHeader className="space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="bg-indigo-500/10 text-indigo-400 border-indigo-500/20 text-[10px] uppercase font-bold">
              AI Environment System
            </Badge>
          </div>
          <DialogTitle className="text-xl font-extrabold text-white tracking-tight flex items-center justify-between">
            <span>Campaign AI Environment Manager</span>
          </DialogTitle>
          <DialogDescription className="text-xs text-slate-400">
            Set the active campaign environment or ingest a raw brief to synthesize tailored extraction prompts.
          </DialogDescription>
        </DialogHeader>

        {/* Tab Switcher */}
        <div className="flex gap-2 p-1 bg-slate-950 rounded-2xl border border-slate-800">
          <button
            type="button"
            onClick={() => setTab("switch")}
            className={`flex-1 py-2 rounded-xl text-xs font-extrabold transition-all ${
              tab === "switch" ? "bg-indigo-600 text-white shadow-lg" : "text-slate-400 hover:text-white"
            }`}
          >
            Switch Active Campaign ({campaigns.length})
          </button>
          <button
            type="button"
            onClick={() => setTab("ingest")}
            className={`flex-1 py-2 rounded-xl text-xs font-extrabold transition-all ${
              tab === "ingest" ? "bg-indigo-600 text-white shadow-lg" : "text-slate-400 hover:text-white"
            }`}
          >
            ✨ Ingest Brief with AI
          </button>
        </div>

        {/* TAB 1: SWITCH CAMPAIGN */}
        {tab === "switch" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 max-h-80 overflow-y-auto custom-scrollbar pr-1">
              {campaigns.map((c) => {
                const isActive = c.id === activeCampaignId;
                return (
                  <Card
                    key={c.id}
                    className={`border transition-all cursor-pointer p-4 rounded-2xl ${
                      isActive
                        ? "bg-indigo-950/40 border-indigo-500/50 ring-2 ring-indigo-500/20"
                        : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                    }`}
                    onClick={async () => {
                      await onSelectCampaign(c.id);
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <h4 className="font-extrabold text-sm text-white">{c.name}</h4>
                          {isActive && (
                            <Badge variant="emerald" className="text-[10px] font-bold">
                              🔥 Active
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-slate-400 line-clamp-2 italic">
                          "{c.brief ? c.brief.slice(0, 100) : "Custom AI Extraction Environment Profile"}"
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant={isActive ? "emerald" : "outline"}
                        className="rounded-xl text-xs shrink-0"
                      >
                        {isActive ? <Check className="w-3.5 h-3.5 mr-1" /> : "Select"}
                        {isActive ? "Active" : "Switch"}
                      </Button>
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 2: INGEST BRIEF WITH AI */}
        {tab === "ingest" && (
          <div className="space-y-4">
            {!analyzedResult ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-[11px] uppercase font-bold text-slate-400 block">Campaign Name (Optional)</label>
                  <input
                    type="text"
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                    placeholder="e.g. Creator Alpha / Mindset Mastery"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-white text-xs font-medium outline-none focus:border-indigo-500"
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] uppercase font-bold text-slate-400">Raw Brief Text / Markdown</label>
                    <label className="text-xs text-indigo-400 hover:underline cursor-pointer flex items-center gap-1">
                      <Folder className="w-3 h-3" /> Upload .md file
                      <input type="file" accept=".md,.txt" className="hidden" onChange={handleFileUpload} />
                    </label>
                  </div>
                  <textarea
                    value={rawBrief}
                    onChange={(e) => setRawBrief(e.target.value)}
                    rows={6}
                    placeholder="Paste the campaign brief from Whop, Notion, or client doc here...&#10;&#10;e.g. Focus on entrepreneurship, high energy podcast moments. Avoid intros and sponsor reads. Target audience: young founders."
                    className="w-full bg-slate-950 border border-slate-800 rounded-2xl p-4 text-xs text-slate-200 font-mono outline-none focus:border-indigo-500 resize-none shadow-inner"
                  />
                </div>

                {errorMsg && (
                  <p className="text-xs text-rose-400 font-medium bg-rose-950/30 p-2.5 rounded-xl border border-rose-900/50">
                    ⚠️ {errorMsg}
                  </p>
                )}

                <Button
                  variant="gradient"
                  onClick={handleAnalyze}
                  disabled={isAnalyzing || !rawBrief.trim()}
                  className="w-full h-12 rounded-2xl font-extrabold text-xs"
                >
                  <Sparkles className="w-4 h-4 mr-2 fill-white" />
                  {isAnalyzing ? "AI Synthesizing Extraction Strategy Profile..." : "Synthesize AI Campaign Profile"}
                </Button>
              </div>
            ) : (
              /* RESULT PREVIEW CARD */
              <div className="space-y-4 animate-fadeIn">
                <Card className="bg-indigo-950/30 border-indigo-500/40 p-5 rounded-2xl space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-extrabold text-sm text-emerald-400 flex items-center gap-1.5">
                      <Check className="w-4 h-4" /> AI Strategy Profile Created!
                    </h4>
                    <Badge variant="emerald" className="text-[10px]">Activated</Badge>
                  </div>

                  <div className="space-y-2 text-xs">
                    <div>
                      <span className="text-slate-400 font-bold uppercase text-[10px] block">Custom System Prompt</span>
                      <p className="text-slate-200 bg-slate-950 p-2.5 rounded-xl border border-slate-800 font-mono text-[11px]">
                        {analyzedResult.custom_system_prompt}
                      </p>
                    </div>

                    {analyzedResult.whop_metadata && (
                      <div className="grid grid-cols-2 gap-2 pt-2 border-t border-indigo-900/40">
                        <div>
                          <span className="text-slate-400 font-bold text-[10px]">Creator Handle</span>
                          <p className="text-indigo-300 font-bold">{analyzedResult.whop_metadata.creator_handle}</p>
                        </div>
                        <div>
                          <span className="text-slate-400 font-bold text-[10px]">Hashtag Stack</span>
                          <p className="text-purple-300 font-mono text-[10px]">{analyzedResult.whop_metadata.hashtags}</p>
                        </div>
                      </div>
                    )}
                  </div>
                </Card>

                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setAnalyzedResult(null)}
                    className="rounded-xl text-xs border-slate-800 text-slate-300"
                  >
                    Create Another
                  </Button>
                  <Button
                    variant="gradient"
                    onClick={onClose}
                    className="rounded-xl text-xs font-bold"
                  >
                    Done & Apply to App
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
