'use client';
import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';

// Toggles the .dark class set by the layout init script. Renders a stable
// placeholder until mounted so server and client HTML match.
export function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark' | null>(null);
  useEffect(() => {
    setTheme(document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  }, []);
  if (theme === null) {
    return (
      <Button type="button" variant="ghost" disabled aria-label="Toggle theme">
        <Sun size={16} aria-hidden />
      </Button>
    );
  }
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <Button
      type="button"
      variant="ghost"
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      onClick={() => {
        document.documentElement.classList.toggle('dark', next === 'dark');
        try {
          localStorage.setItem('launchcrew-theme', next);
        } catch {
          // Private mode: theme still applies for this visit.
        }
        setTheme(next);
      }}
    >
      {theme === 'dark' ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
    </Button>
  );
}
