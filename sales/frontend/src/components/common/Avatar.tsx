import clsx from 'clsx';
import { Avatar as DiceAvatar, Style } from '@dicebear/core';
import micahDefinition from '@dicebear/styles/micah.json';
import { initials } from '../../utils/format';

const DARK_BG = ['#1f2a14', '#22251f', '#2a2416', '#18242a', '#26201f', '#1d2620'];
const DARK_INK = ['#C7F33C', '#E1F2AE', '#E0A93B', '#7FB2E5', '#D9A79F', '#A9D6B5'];
const LIGHT_BG = ['#E8F5C8', '#ECEEE6', '#F7EBD2', '#DDEBF7', '#F5E3E0', '#DFF0E3'];
const LIGHT_INK = ['#3F6B05', '#4A5244', '#8A5A00', '#24598F', '#8F453B', '#2F6B44'];
const light = () => typeof document !== 'undefined' && document.documentElement.dataset.mode === 'light';
const hash = (s: string) => s.split('').reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7);

export function CompanyAvatar({ name, size = 36 }: { name: string; size?: number }) {
  const i = hash(name) % 6;
  return (
    <span className="inline-flex items-center justify-center rounded-xl font-display font-semibold shrink-0 border border-white/5"
      style={{ width: size, height: size, background: (light() ? LIGHT_BG : DARK_BG)[i], color: (light() ? LIGHT_INK : DARK_INK)[i], fontSize: size * 0.34 }} aria-hidden>
      {initials(name)}
    </span>
  );
}

// --- contact portraits ------------------------------------------------------------
// DiceBear "Micah" (remix of "Avatar Illustration System" by Micah Lanier, CC BY 4.0),
// rendered in the browser from the name — no network request, so names never leave the app.
// Decorative only: not a depiction of the real person.

const micah = new Style(micahDefinition as ConstructorParameters<typeof Style>[0]);
const cache = new Map<string, string>();

function portraitUri(name: string): string {
  const seed = name.trim().toLowerCase();
  let uri = cache.get(seed);
  if (!uri) {
    uri = new DiceAvatar(micah, { seed }).toDataUri();
    if (cache.size > 2000) cache.clear();
    cache.set(seed, uri);
  }
  return uri;
}

export function ContactAvatar({ name, size = 32, className }: { name: string; size?: number; className?: string }) {
  return (
    <img src={portraitUri(name || '?')} width={size} height={size} alt={name} title={name} loading="lazy"
      className={clsx('rounded-full shrink-0 border border-black/5 object-cover', className)} style={{ width: size, height: size }} />
  );
}
