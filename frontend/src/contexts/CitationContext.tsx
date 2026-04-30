import { createContext, useContext, useState } from 'react';

interface CitationContextType {
  focusedRef: any; // CitedRef | null
  setFocusedRef: (ref: any) => void; // (ref: CitedRef | null) => void
  conversationRefs: any[]; // CitedRef[]
  setConversationRefs: (refs: any[]) => void; // (refs: CitedRef[]) => void
  channelName: string;
  setChannelName: (name: string) => void;
}

const CitationContext = createContext<CitationContextType | undefined>(undefined);

export function useCitation() {
  const context = useContext(CitationContext);
  if (!context) {
    throw new Error('useCitation must be used within a CitationProvider');
  }
  return context;
}

export function CitationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [focusedRef, setFocusedRef] = useState<any>(null);
  const [conversationRefs, setConversationRefs] = useState<any[]>([]);
  const [channelName, setChannelName] = useState<string>('');

  return (
    <CitationContext.Provider
      value={{
        focusedRef,
        setFocusedRef,
        conversationRefs,
        setConversationRefs,
        channelName,
        setChannelName,
      }}
    >
      {children}
    </CitationContext.Provider>
  );
}