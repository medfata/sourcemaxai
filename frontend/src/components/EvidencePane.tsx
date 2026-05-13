import { useState } from 'react';
import type { ChatSource, ProfileVideo } from '../types';

interface CitedRef {
  sourceId?: string;
  videoId: string;
  startSeconds: number;
  messageIdx: number;
  profileVideo?: ProfileVideo;
  evidenceQuote?: string;
  title?: string;
  uploadDate?: string;
  source?: ChatSource;
}

interface Props {
  focusedRef: CitedRef | null;
  conversationRefs: CitedRef[];
  onSelectRef: (ref: CitedRef) => void;
  channelName: string;
}

export default function EvidencePane({
  focusedRef,
  conversationRefs,
  onSelectRef,
  channelName: _channelName,
}: Props) {
  const [tab, setTab] = useState<'sources' | 'videos'>('sources');
  const titleForRef = (ref: CitedRef) => ref.profileVideo?.title ?? ref.title ?? ref.source?.title ?? 'Unknown video';
  const dateForRef = (ref: CitedRef) => ref.profileVideo?.upload_date ?? ref.uploadDate ?? ref.source?.upload_date ?? '';
  const quoteForRef = (ref: CitedRef) => ref.evidenceQuote ?? ref.source?.quote;
  const labelForRef = (ref: CitedRef) =>
    ref.sourceId
      ? `[${ref.sourceId}] ${Math.floor(ref.startSeconds / 60)}:${String(ref.startSeconds % 60).padStart(2, '0')}`
      : `[↗ ${Math.floor(ref.startSeconds / 60)}:${String(ref.startSeconds % 60).padStart(2, '0')}]`;

  if (conversationRefs.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center px-6 text-center">
        <span className="text-[11px] font-mono uppercase tracking-[0.22em] text-ink-300 dark:text-white/30 mb-3">Evidence</span>
        <p className="font-display text-[22px] tracking-tight text-ink-700 dark:text-white/70 leading-tight max-w-[240px]">
          Citations will appear here as answers stream in.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-black/[0.06] dark:border-white/10 px-2 pt-2 gap-1">
        <button
          onClick={() => setTab('sources')}
          className={`relative flex-1 px-3 py-2.5 text-[13px] font-medium rounded-xl transition-colors ${
            tab === 'sources'
              ? 'text-ink-900 dark:text-cream bg-ink-100 dark:bg-white/[0.06]'
              : 'text-ink-400 hover:text-ink-700 dark:hover:text-white/70'
          }`}
        >
          Sources
        </button>
        <button
          onClick={() => setTab('videos')}
          className={`relative flex-1 px-3 py-2.5 text-[13px] font-medium rounded-xl transition-colors ${
            tab === 'videos'
              ? 'text-ink-900 dark:text-cream bg-ink-100 dark:bg-white/[0.06]'
              : 'text-ink-400 hover:text-ink-700 dark:hover:text-white/70'
          }`}
        >
          Videos cited
        </button>
      </div>

      {tab === 'sources' ? (
        <div className="flex-1 overflow-y-auto p-4">
          {focusedRef ? (
            <>
              <div className="aspect-video w-full mb-4">
                <iframe
                  key={`${focusedRef.videoId}-${focusedRef.startSeconds}`}
                  title="YouTube video player"
                  src={`https://www.youtube.com/embed/${focusedRef.videoId}?start=${focusedRef.startSeconds}&autoplay=1&rel=0`}
                  allowFullScreen
                  className="w-full h-full rounded-xl"
                />
              </div>

              <div className="mb-4">
                {quoteForRef(focusedRef) ? (
                  <blockquote className="border-l-2 border-accent-red/50 pl-4 py-1 italic text-[14px] leading-relaxed text-ink-700 dark:text-white/75">
                    {quoteForRef(focusedRef)}
                  </blockquote>
                ) : (
                  <p className="text-ink-400 italic text-[13px]">
                    No quote captured for this source.
                  </p>
                )}
              </div>

              <div className="flex overflow-x-auto mb-4 space-x-2">
                {conversationRefs
                  .filter((r) => r.messageIdx === focusedRef?.messageIdx)
                  .map((r, idx) => (
                    <button
                      key={idx}
                      onClick={() => onSelectRef(r)}
                      className={`text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap flex-shrink-0 transition-colors ${
                        r.messageIdx === focusedRef.messageIdx &&
                        ((r.sourceId && r.sourceId === focusedRef.sourceId) ||
                          (r.videoId === focusedRef.videoId &&
                            r.startSeconds === focusedRef.startSeconds))
                          ? 'bg-ink-900 dark:bg-cream text-cream dark:text-ink-900'
                          : 'bg-white dark:bg-ink-700 border border-black/[0.06] dark:border-white/10 text-ink-700 dark:text-white/70 hover:border-accent-red/40'
                      }`}
                    >
                      {labelForRef(r)} — {titleForRef(r)}
                    </button>
                  ))}
              </div>

              <div className="border-t border-black/[0.06] dark:border-white/10 pt-4">
                <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-3">Cited in conversation</p>
                <div className="space-y-1">
                  {Array.from(new Map(conversationRefs.map((r) => [r.videoId, r])).values()).map((ref, idx) => (
                    <button
                      key={idx}
                      className="w-full flex items-center gap-3 p-2 hover:bg-ink-100 dark:hover:bg-white/[0.04] rounded-xl text-left transition-colors"
                      onClick={() => onSelectRef(ref)}
                    >
                      <img
                        src={`https://i.ytimg.com/vi/${ref.videoId}/mqdefault.jpg`}
                        alt={ref.profileVideo?.title ?? ''}
                        className="w-14 h-9 rounded-md object-cover flex-shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-medium text-ink-900 dark:text-cream truncate">
                          {titleForRef(ref)}
                        </div>
                        <div className="text-[11px] text-ink-400 mt-0.5">{dateForRef(ref)}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <p className="text-ink-400 text-[13px]">Click a citation to view evidence.</p>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-300 mb-3">Videos cited</p>
          <div className="space-y-1">
            {Array.from(new Map(conversationRefs.map((r) => [r.videoId, r])).values()).map((ref, idx) => {
              const cnt = conversationRefs.filter((r) => r.videoId === ref.videoId).length
              return (
                <button
                  key={idx}
                  className="w-full flex items-center gap-3 p-2 hover:bg-ink-100 dark:hover:bg-white/[0.04] rounded-xl text-left transition-colors"
                  onClick={() => onSelectRef(ref)}
                >
                  <img
                    src={`https://i.ytimg.com/vi/${ref.videoId}/mqdefault.jpg`}
                    alt={ref.profileVideo?.title ?? ''}
                    className="w-14 h-9 rounded-md object-cover flex-shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-ink-900 dark:text-cream truncate">{titleForRef(ref)}</div>
                    <div className="text-[11px] text-ink-400 mt-0.5">
                      {dateForRef(ref)} · <span className="font-mono">{cnt}</span> citation{cnt !== 1 ? 's' : ''}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  );
}
