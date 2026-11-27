"use client";

import { useState } from "react";
import { Copy, Check, Calendar, DollarSign, Sparkles, Hash, MessageSquare, Send, ArrowRight, Share2, Layers, Award } from "lucide-react";

interface ClipItem {
  title?: string;
  hook?: string;
  explanation?: string;
  reasoning?: string;
  virality_score?: number;
  start_time?: number | string;
  end_time?: number | string;
}

interface WhopPublisherProps {
  campaignSlug: string;
  clips: ClipItem[];
  activeProfile?: any;
  onExportPackage?: () => void;
}

export function WhopPublisher({ campaignSlug, clips, activeProfile, onExportPackage }: WhopPublisherProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [selectedSort, setSelectedSort] = useState<"virality" | "chronological">("virality");

  const creatorHandle = activeProfile?.whop_metadata?.creator_handle || activeProfile?.creator_handle || `@${campaignSlug}`;
  const hashtagStack = activeProfile?.whop_metadata?.hashtags || `#${campaignSlug} #contentrewards #clipping #viral #fyp`;

  // Sort clips based on selected strategy
  const sortedClips = [...clips].sort((a, b) => {
    if (selectedSort === "virality") {
      return (b.virality_score || 0) - (a.virality_score || 0);
    }
    return parseFloat(String(a.start_time || 0)) - parseFloat(String(b.start_time || 0));
  });

  const generatePostingSlot = (index: number) => {
    const today = new Date();
    const dayOffset = Math.floor(index / 2);
    const slotTime = index % 2 === 0 ? "12:00 PM EST (Slot 1)" : "07:00 PM EST (Slot 2)";
    const date = new Date(today);
    date.setDate(today.getDate() + dayOffset);
    return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })} — ${slotTime}`;
  };

  const handleCopyCaption = (clip: ClipItem, index: number) => {
    const title = clip.title || "Viral Insight Breakdown";
    const hashtags = "#business #entrepreneurship #mindset #clipfactory #contentrewards";
    const pinnedComment = "🔥 Want more breakdowns like this? Check out the full community link in bio!";
    
    const captionText = `${title}\n\n${hashtags}\n\n👇 Pinned Comment:\n${pinnedComment}`;
    navigator.clipboard.writeText(captionText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2500);
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Studio Header Card */}
      <div className="relative overflow-hidden bg-gradient-to-r from-emerald-950/60 via-slate-900 to-indigo-950/60 border border-emerald-500/20 rounded-3xl p-6 backdrop-blur-xl shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative z-10">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-3 py-1 rounded-full text-xs font-extrabold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 glow-emerald">
                <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                Whop Content Rewards Mode
              </span>
              <span className="text-xs text-slate-400 font-mono">Campaign: <strong className="text-white">{campaignSlug}</strong></span>
            </div>
            <h2 className="text-2xl font-black text-white tracking-tight">
              Payout Schedule & 1-Click Caption Generator
            </h2>
            <p className="text-xs text-slate-400 mt-1 max-w-xl">
              Auto-generate viral-optimized titles, 3-layer hashtag stacks, and daily posting slot times (12:00 PM & 07:00 PM EST) matching Whop Content Rewards submission guidelines.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            {onExportPackage && (
              <button
                type="button"
                onClick={onExportPackage}
                className="px-5 py-3 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-extrabold text-xs flex items-center justify-center gap-2 shadow-lg transition-all cursor-pointer"
              >
                <DollarSign className="w-4 h-4 fill-white" />
                Export 7-Day Whop Package
              </button>
            )}
            <div className="flex items-center gap-3 bg-slate-950/80 p-2 rounded-2xl border border-slate-800">
              <button
                onClick={() => setSelectedSort("virality")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                  selectedSort === "virality"
                    ? "bg-emerald-500 text-slate-950 shadow-md"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                🔥 Sort Virality First
              </button>
              <button
                onClick={() => setSelectedSort("chronological")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                  selectedSort === "chronological"
                    ? "bg-emerald-500 text-slate-950 shadow-md"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                ⏱️ Chronological
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Grid of Clip Submission Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {sortedClips.length === 0 ? (
          <div className="col-span-full py-16 text-center bg-slate-900/60 border border-dashed border-slate-800 rounded-3xl backdrop-blur-xl">
            <Sparkles className="w-12 h-12 text-slate-600 mx-auto mb-3 opacity-40 animate-pulse" />
            <h3 className="text-base font-bold text-slate-300">No Extracted Clips Available</h3>
            <p className="text-xs text-slate-500 mt-1">Run a clip extraction in the Extraction Workspace tab to populate Whop Rewards captions.</p>
          </div>
        ) : (
          sortedClips.map((clip, index) => {
            const isCopied = copiedIndex === index;
            const slotText = generatePostingSlot(index);
            const score = clip.virality_score || 8.5;

            return (
              <div
                key={index}
                className="group relative bg-slate-900/80 border border-slate-800/80 hover:border-emerald-500/40 rounded-2xl p-5 backdrop-blur-xl transition-all duration-300 shadow-xl flex flex-col justify-between"
              >
                <div>
                  {/* Top Metadata Line */}
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-950 text-[10px] font-mono font-bold text-slate-300 border border-slate-800">
                      <Calendar className="w-3 h-3 text-emerald-400" />
                      {slotText}
                    </span>

                    <span className="flex items-center gap-1 text-xs font-black text-amber-400 bg-amber-500/10 px-2.5 py-1 rounded-lg border border-amber-500/20">
                      <Award className="w-3.5 h-3.5 text-amber-400" />
                      {score.toFixed(1)} / 10
                    </span>
                  </div>

                  {/* Title & Hook */}
                  <h3 className="text-base font-extrabold text-white group-hover:text-emerald-400 transition-colors line-clamp-2 mb-2">
                    {clip.title || `Clip #${index + 1}`}
                  </h3>

                  {clip.hook && (
                    <div className="bg-slate-950/70 rounded-xl p-3 border border-slate-800 mb-3">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block mb-1">
                        Viral Hook Line
                      </span>
                      <p className="text-xs text-slate-300 italic leading-relaxed">
                        "{clip.hook}"
                      </p>
                    </div>
                  )}

                  {/* Hashtag Stack Pills */}
                  <div className="flex flex-wrap gap-1.5 mb-4">
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      #entrepreneurship
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/20">
                      #business
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      #clipfactory
                    </span>
                  </div>
                </div>

                {/* Copy Button Action */}
                <button
                  onClick={() => handleCopyCaption(clip, index)}
                  className={`w-full py-2.5 rounded-xl font-bold text-xs transition-all duration-200 flex items-center justify-center gap-2 cursor-pointer ${
                    isCopied
                      ? "bg-emerald-500 text-slate-950 shadow-lg shadow-emerald-500/25"
                      : "bg-slate-800 hover:bg-emerald-600 text-white hover:text-white border border-slate-700 hover:border-emerald-500"
                  }`}
                >
                  {isCopied ? (
                    <>
                      <Check className="w-4 h-4" /> Caption & Hashtags Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="w-4 h-4" /> Copy Whop Submission Caption
                    </>
                  )}
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
