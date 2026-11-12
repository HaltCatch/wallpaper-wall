export interface ScrollRail {
  update: () => void;
}

/** The glowing draggable scroll indicator on the right edge of the wall. */
export function createScrollRail(): ScrollRail {
  const rail = document.createElement('div');
  rail.className = 'scroll-rail';
  rail.innerHTML = '<div class="scroll-track"><div class="scroll-thumb"></div></div>';
  const track = rail.querySelector<HTMLElement>('.scroll-track')!;
  const thumb = rail.querySelector<HTMLElement>('.scroll-thumb')!;
  const update = () => {
    const trackHeight = track.clientHeight;
    const maximum = Math.max(1, document.documentElement.scrollHeight - innerHeight);
    const thumbSize = 30;
    const offset = (trackHeight - thumbSize) * (scrollY / maximum);
    thumb.style.setProperty('--thumb-y', `${offset}px`);
  };
  const seek = (event: PointerEvent) => {
    const rect = track.getBoundingClientRect();
    const thumbHeight = thumb.getBoundingClientRect().height;
    const ratio = Math.max(0, Math.min(1, (event.clientY - rect.top - thumbHeight / 2) / Math.max(1, rect.height - thumbHeight)));
    window.scrollTo({ top: ratio * (document.documentElement.scrollHeight - innerHeight), behavior: 'auto' });
  };
  rail.addEventListener('pointerdown', (event) => {
    rail.setPointerCapture(event.pointerId);
    rail.classList.add('is-dragging');
    seek(event);
  });
  rail.addEventListener('pointermove', (event) => {
    if (rail.classList.contains('is-dragging')) seek(event);
  });
  const release = () => rail.classList.remove('is-dragging');
  rail.addEventListener('pointerup', release);
  rail.addEventListener('pointercancel', release);
  document.body.append(rail);
  requestAnimationFrame(update);
  return { update };
}
