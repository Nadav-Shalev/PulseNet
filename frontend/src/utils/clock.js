import { useSyncExternalStore } from 'react';

// One shared clock for every relative timestamp on screen ("5 minutes ago"), so the
// times stay true while the page is open. A single setInterval runs while at least
// one timestamp is mounted and stops with the last one: never one timer per card.
// A tick only re-renders the subscribers; it makes no request.
export const CLOCK_TICK_MS = 60_000;

const listeners = new Set();
let ticks = 0;
let timer = null;

function tick() {
  ticks += 1;
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  if (timer === null) timer = setInterval(tick, CLOCK_TICK_MS);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      clearInterval(timer);
      timer = null;
    }
  };
}

const getTicks = () => ticks;

// Re-renders the calling component on every tick. The text itself is still computed
// from the real Date.now() at render, so a card mounted between ticks is never stale.
export function useClockTick() {
  return useSyncExternalStore(subscribe, getTicks);
}
