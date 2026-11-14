import { useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { echarts, registerTheme } from './theme';

let themeName: string | null = null;

/**
 * Thin wrapper around echarts/core — no echarts-for-react dependency.
 * Re-registers the theme on colour-scheme change so dark mode is a real re-theme, not a filter.
 */
export function Chart({ option, height = 260, ariaLabel, onClick }:
  { option: EChartsOption; height?: number; ariaLabel: string; onClick?: (params: any) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts>();
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!el.current) return;
    themeName ??= registerTheme();
    inst.current = echarts.init(el.current, themeName, { renderer: 'canvas' });
    inst.current.on('click', (p: any) => clickRef.current?.(p));
    const onResize = () => inst.current?.resize();
    window.addEventListener('resize', onResize);
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => {
      inst.current?.dispose();
      themeName = registerTheme();
      inst.current = echarts.init(el.current!, themeName, { renderer: 'canvas' });
      inst.current.on('click', (p: any) => clickRef.current?.(p));
      inst.current.setOption(option);
    };
    mq.addEventListener('change', onScheme);
    return () => {
      window.removeEventListener('resize', onResize);
      mq.removeEventListener('change', onScheme);
      inst.current?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { inst.current?.setOption(option, true); }, [option]);

  return <div ref={el} style={{ height }} role="img" aria-label={ariaLabel} />;
}
