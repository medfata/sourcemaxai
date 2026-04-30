import { useState } from 'react';
import type { ProfileVideo } from '../types';

interface CitedRef {
  videoId: string;
  startSeconds: number;
  messageIdx: number;
  profileVideo?: ProfileVideo;
  evidenceQuote?: string;
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

  if (conversationRefs.length === 0) {
    return (
      <div className="p-4 text-center text-ios-text-secondary">
        Citations will appear here as the assistant answers.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-l border-ios-separator/60 bg-white dark:bg-ios-card-dark">
      <div className="flex border-b border-ios-separator/60">
        <button
          onClick={() => setTab('sources')}
          className={`flex-1 px-3 py-2 text-sm font-medium ${
            tab === 'sources'
              ? 'text-ios-text-primary border-b-2 border-ios-blue'
              : 'text-ios-text-secondary hover:text-ios-text-primary'
          }`}
        >
          Sources
        </button>
        <button
          onClick={() => setTab('videos')}
          className={`flex-1 px-3 py-2 text-sm font-medium ${
            tab === 'videos'
              ? 'text-ios-text-primary border-b-2 border-ios-blue'
              : 'text-ios-text-secondary hover:text-ios-text-primary'
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
                {focusedRef.profileVideo ? (
                  <iframe
                    key={`${focusedRef.videoId}-${focusedRef.startSeconds}`}
                    title="YouTube video player"
                    src={`https://www.youtube.com/embed/${focusedRef.videoId}?start=${focusedRef.startSeconds}&autoplay=1&rel=0`}
                    allowFullScreen
                    className="w-full h-full rounded-xl"
                  />
                ) : (
                  <div className="w-full h-full rounded-xl bg-black/10 flex items-center justify-center text-ios-text-secondary text-sm">
                    Video not in profile
                  </div>
                )}
              </div>

              <div className="mb-4">
                {focusedRef.evidenceQuote ? (
                  <blockquote className="border-l-2 border-ios-blue/40 pl-3 italic">
                    {focusedRef.evidenceQuote}
                  </blockquote>
                ) : (
                  <p className="text-ios-text-secondary italic">
                    No quote captured for this timestamp.
                  </p>
                )}
              </div>

              <div className="flex overflow-x-auto mb-4 space-x-2">
                {conversationRefs
                  .filter(
                    (r) =>
                      r.messageIdx === focusedRef?.messageIdx &&
                      r.videoId === focusedRef.videoId &&
                      r.startSeconds === focusedRef.startSeconds
                  )
                  .map((r, idx) => (
                    <button
                      key={idx}
                      onClick={() => onSelectRef(r)}
                      className={`text-xs px-2 py-1 rounded ${
                        r === focusedRef
                          ? 'bg-ios-blue text-white'
                          : 'bg-white border border-ios-separator hover:bg-ios-blue/5'
                      }`}
                    >
                      [↗ {Math.floor(r.startSeconds / 60)}:{String(
                        r.startSeconds % 60
                      ).padStart(2, '0')} — {r.profileVideo?.title ?? 'Unknown video'}]
                    </button>
                  ))}
              </div>

              <div className="border-t border-ios-separator/60 pt-4">
                <h3 className="text-sm font-semibold mb-2">Cited videos in this conversation</h3>
                <div className="space-y-2">
                  {Array.from(
                    new Map(
                      conversationRefs
                        .filter((r) => r.profileVideo)
                        .map((r) => [r.videoId, r])
                    ).values()
                  ).map((ref, idx) => (
                    <div
                      key={idx}
                      className="flex items-center space-x-2 p-2 hover:bg-ios-blue/5 rounded"
                      onClick={() => onSelectRef(ref)}
                    >
                      <img
                        src={`https://i.ytimg.com/vi/${ref.videoId}/mqdefault.jpg`}
                        alt={ref.profileVideo?.title ?? ''}
                        className="w-10 h-6 rounded"
                      />
                      <div>
                        <div className="font-medium text-ios-text-primary">
                          {ref.profileVideo?.title ?? 'Unknown video'}
                        </div>
                        <div className="text-xs text-ios-text-secondary">
                          {ref.profileVideo?.upload_date ?? ''}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <p className="text-ios-text-secondary">Click a citation to view evidence</p>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <h3 className="text-sm font-semibold mb-4">Videos cited in this conversation</h3>
          <div className="space-y-2">
            {Array.from(
              new Map(
                conversationRefs
                  .filter((r) => r.profileVideo)
                  .map((r) => [r.videoId, r])
              ).values()
            ).map((ref, idx) => (
              <div
                key={idx}
                className="flex items-center space-x-2 p-2 hover:bg-ios-blue/5 rounded"
                onClick={() => onSelectRef(ref)}
              >
                <img
                  src={`https://i.ytimg.com/vi/${ref.videoId}/mqdefault.jpg`}
                  alt={ref.profileVideo?.title ?? ''}
                  className="w-10 h-6 rounded"
                />
                <div>
                  <div className="font-medium text-ios-text-primary">
                    {ref.profileVideo?.title ?? 'Unknown video'}
                  </div>
                  <div className="text-xs text-ios-text-secondary">
                    {ref.profileVideo?.upload_date ?? ''} •
                    {conversationRefs.filter((r) => r.videoId === ref.videoId).length}
                    citation{conversationRefs.filter((r) => r.videoId === ref.videoId).length !== 1 ? 's' : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}