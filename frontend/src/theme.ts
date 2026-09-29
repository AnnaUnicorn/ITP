export type ColorTheme = 'forest' | 'ocean' | 'sunset' | 'violet';
export type ContrastTheme = 'standard' | 'high';

export const colorThemes: { id: ColorTheme; label: string; description: string }[] = [
  { id: 'forest', label: '森林绿', description: '自然沉静' },
  { id: 'ocean', label: '海洋蓝', description: '清爽专注' },
  { id: 'sunset', label: '暖日橙', description: '温暖明亮' },
  { id: 'violet', label: '暮光紫', description: '柔和灵感' },
];

export function loadColorTheme(): ColorTheme {
  try {
    const value = localStorage.getItem('itp-color-theme');
    if (colorThemes.some((item) => item.id === value)) return value as ColorTheme;
  } catch { /* Storage may be unavailable in a private browser session. */ }
  return 'forest';
}

export function loadContrastTheme(): ContrastTheme {
  try { return localStorage.getItem('itp-contrast-theme') === 'high' ? 'high' : 'standard'; }
  catch { return 'standard'; }
}

export function applyTheme(color: ColorTheme, contrast: ContrastTheme): void {
  document.documentElement.dataset.theme = color;
  document.documentElement.dataset.contrast = contrast;
  try {
    localStorage.setItem('itp-color-theme', color);
    localStorage.setItem('itp-contrast-theme', contrast);
  } catch { /* The current page can still use the selected theme. */ }
}
