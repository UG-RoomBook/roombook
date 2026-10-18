import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from './ThemeProvider';
import { AppearanceControl } from './AppearanceControl';
import { APPEARANCE_STORAGE_KEY, useTheme } from './theme-context';

let systemDark = false;
const listeners = new Set<() => void>();

beforeEach(() => {
  systemDark = false;
  listeners.clear();
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      get matches() {
        return query.includes('color-scheme') && systemDark;
      },
      media: query,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })),
  );
});

function ThemeState() {
  const { resolvedTheme } = useTheme();
  const [input, setInput] = useState('');
  return (
    <>
      <AppearanceControl />
      <output aria-label="Resolved theme">{resolvedTheme}</output>
      <label>
        Notes
        <input value={input} onChange={(event) => setInput(event.target.value)} />
      </label>
    </>
  );
}

function renderTheme() {
  return render(
    <ThemeProvider>
      <ThemeState />
    </ThemeProvider>,
  );
}

describe('appearance', () => {
  it('persists an explicit choice and preserves current form values', async () => {
    renderTheme();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Notes'), 'Keep this input');
    await user.click(screen.getByRole('button', { name: 'Dark' }));
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
    expect(localStorage.getItem(APPEARANCE_STORAGE_KEY)).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
    expect(screen.getByLabelText('Notes')).toHaveValue('Keep this input');
  });

  it('restores a saved preference before rendering the application', () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, 'dark');
    renderTheme();
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('follows live system changes only when System is selected', async () => {
    renderTheme();
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('light');
    act(() => {
      systemDark = true;
      listeners.forEach((listener) => listener());
    });
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
    await userEvent.click(screen.getByRole('button', { name: 'Light' }));
    act(() => {
      systemDark = false;
      listeners.forEach((listener) => listener());
      systemDark = true;
      listeners.forEach((listener) => listener());
    });
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('light');
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
  });

  it('falls back to System for invalid stored preferences', () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, 'invalid');
    renderTheme();
    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('synchronizes appearance changes from another browser tab', () => {
    renderTheme();
    act(() =>
      fireEvent(
        window,
        new StorageEvent('storage', { key: APPEARANCE_STORAGE_KEY, newValue: 'dark' }),
      ),
    );
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
    act(() =>
      fireEvent(
        window,
        new StorageEvent('storage', { key: APPEARANCE_STORAGE_KEY, newValue: null }),
      ),
    );
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('light');
  });

  it('allows keyboard activation of appearance options', async () => {
    renderTheme();
    screen.getByRole('button', { name: 'Light' }).focus();
    await userEvent.keyboard('{Tab}{Enter}');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps appearance controls usable when storage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Storage blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('Storage blocked');
    });
    renderTheme();
    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    expect(screen.getByLabelText('Resolved theme')).toHaveTextContent('dark');
  });
});
