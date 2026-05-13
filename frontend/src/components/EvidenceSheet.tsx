import { useEffect } from 'react';
import EvidencePane from './EvidencePane';

interface Props {
  focusedRef: any; // CitedRef | null
  conversationRefs: any[]; // CitedRef[]
  onSelectRef: (ref: any) => void; // (ref: CitedRef) => void
  channelName: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function EvidenceSheet({
  focusedRef,
  conversationRefs,
  onSelectRef,
  channelName,
  isOpen,
  onClose,
}: Props) {
  // Handle outside clicks to close the sheet
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (isOpen && target && !target.closest('[data-sheet-content]')) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-stretch sm:justify-end bg-black/50 backdrop-blur-sm">
      <div
        data-sheet-content
        className="relative w-full max-w-lg sm:w-[440px] sm:max-w-[440px] sm:h-full bg-white dark:bg-ios-card-dark rounded-t-3xl sm:rounded-t-none sm:rounded-l-3xl shadow-xl p-4 transform transition-transform duration-300 ease-out translate-y-0 sm:translate-x-0 flex flex-col"
      >
        <div className="flex justify-between items-start mb-4 flex-shrink-0">
          <h3 className="text-lg font-semibold text-ios-text-primary dark:text-ios-text-primary-dark">
            Evidence
          </h3>
          <button
            onClick={onClose}
            className="h-8 w-8 rounded-full bg-black/[0.04] dark:bg-white/[0.08] text-ios-text-secondary hover:text-ios-blue flex items-center justify-center"
            aria-label="Close evidence"
          >
            ×
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <EvidencePane
            focusedRef={focusedRef}
            conversationRefs={conversationRefs}
            onSelectRef={onSelectRef}
            channelName={channelName}
          />
        </div>
      </div>
    </div>
  );
}
