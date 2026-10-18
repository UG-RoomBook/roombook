import { createContext, useContext } from 'react';

export type Appearance = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export const APPEARANCE_STORAGE_KEY = 'roombook.appearance';
export const ThemeContext = createContext<{
  appearance: Appearance;
  resolvedTheme: ResolvedTheme;
  setAppearance: (appearance: Appearance) => void;
} | null>(null);

export function isAppearance(value: unknown): value is Appearance {
  return value === 'light' || value === 'dark' || value === 'system';
}

export function readAppearance(): Appearance {
  try {
    const value = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    return isAppearance(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme requires ThemeProvider');
  return context;
}
