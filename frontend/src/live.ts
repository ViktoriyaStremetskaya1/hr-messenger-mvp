import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

/** Подписка на события сервера (SSE): новые сообщения и статусы обновляют чаты без перезагрузки. */
export function useLiveEvents(enabled: boolean) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const es = new EventSource('/api/events/stream');
    es.onmessage = () => {
      // склеиваем пачку событий (статусы приходят очередью) в одно обновление
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        void qc.invalidateQueries({ queryKey: ['inbox'] });
        void qc.invalidateQueries({ queryKey: ['inbox-counts'] });
        void qc.invalidateQueries({ queryKey: ['conversation'] });
      }, 300);
    };
    return () => { es.close(); if (timer) clearTimeout(timer); };
  }, [enabled, qc]);
}
