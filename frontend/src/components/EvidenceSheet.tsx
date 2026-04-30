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
    <div className="fixed inset-0 z-50 flex items-end bg-black/50 backdrop-blur-sm">
      <div
        data-sheet-content
        className="relative w-full max-w-lg bg-white dark:bg-ios-card-dark rounded-t-3xl shadow-xl p-4 transform transition-transform duration-300 ease-out translate-y-0"
      >
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-semibold text-ios-text-primary">
            Evidence
          </h3>
          <button
            onClick={onClose}
            className="text-ios-text-secondary hover:text-ios-blue"
          >
            ×
          </button>
        </div>
        <EvidencePane
          focusedRef={focusedRef}
          conversationRefs={conversationRefs}
          onSelectRef={onSelectRef}
          channelName={channelName}
        />
      </div>
    </div>
  );
}