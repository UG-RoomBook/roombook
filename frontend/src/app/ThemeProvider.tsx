import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import {
  APPEARANCE_STORAGE_KEY,
  isAppearance,
  readAppearance,
  ThemeContext,
  type Appearance,
  type ResolvedTheme,
} from './theme-context';

const darkPreference = '(prefers-color-scheme: dark)';
function subscribeToSystemTheme(onChange: () => void) {
  const media = window.matchMedia(darkPreference);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}
const getSystemTheme = () => window.matchMedia(darkPreference).matches;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [appearance, setPreference] = useState<Appearance>(readAppearance);
  const systemDark = useSyncExternalStore(subscribeToSystemTheme, getSystemTheme, () => false);
  const resolvedTheme: ResolvedTheme =
    appearance === 'dark' || (appearance === 'system' && systemDark) ? 'dark' : 'light';

  const setAppearance = useCallback((next: Appearance) => {
    setPreference(next);
    try {
      window.localStorage.setItem(APPEARANCE_STORAGE_KEY, next);
    } catch {
      // Appearance still works when browser storage is unavailable.
    }
  }, []);

  useEffect(() => {
    const syncPreference = (event: StorageEvent) => {
      if (event.key === APPEARANCE_STORAGE_KEY || event.key === null) {
        setPreference(isAppearance(event.newValue) ? event.newValue : 'system');
      }
    };
    window.addEventListener('storage', syncPreference);
    return () => window.removeEventListener('storage', syncPreference);
  }, []);

  useLayoutEffect(() => {
    document.documentElement.style.colorScheme = resolvedTheme;
    document.documentElement.dataset.theme = resolvedTheme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', resolvedTheme === 'dark' ? '#121212' : '#f4f3ef');
  }, [resolvedTheme]);

  const value = useMemo(
    () => ({ appearance, resolvedTheme, setAppearance }),
    [appearance, resolvedTheme, setAppearance],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
