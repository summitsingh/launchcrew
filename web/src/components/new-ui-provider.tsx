'use client';

import { createContext, useContext } from 'react';

const NewUIContext = createContext(true);

export function NewUIProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  return <NewUIContext.Provider value={enabled}>{children}</NewUIContext.Provider>;
}

export function useNewUI() {
  return useContext(NewUIContext);
}
