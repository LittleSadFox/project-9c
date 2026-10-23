export const PLAYBACK_RATES = [0.25, 0.5, 1, 2, 4];

export function nextSignedRate(direction, current = 1) {
  const sign = direction < 0 ? -1 : 1;
  const magnitude = Math.abs(current) || 1;
  if (current === 0 || Math.sign(current) !== sign) {
    return sign * 1;
  }
  const index = PLAYBACK_RATES.indexOf(magnitude);
  if (index === -1) {
    return sign * 1;
  }
  const next = PLAYBACK_RATES[Math.min(PLAYBACK_RATES.length - 1, index + 1)];
  return sign * next;
}

export function cycleRate(current = 1) {
  const index = PLAYBACK_RATES.indexOf(Math.abs(current) || 1);
  const next = PLAYBACK_RATES[(index + 1) % PLAYBACK_RATES.length];
  return Math.sign(current || 1) * next;
}
