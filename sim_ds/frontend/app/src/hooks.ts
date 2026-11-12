import { useCallback, useEffect, useRef, useState } from "react";
import type { Page } from "./types";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    setError(null);
    loader()
      .then((value) => {
        if (alive.current) setData(value);
      })
      .catch((reason: unknown) => {
        if (alive.current) setError(reason instanceof Error ? reason.message : "加载失败");
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, loading, error, reload: () => setTick((value) => value + 1) };
}

export interface CursorState<T> {
  items: T[];
  next: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  reload: () => void;
  loadMore: () => void;
}

export function useCursorList<T>(
  loader: (cursor?: string) => Promise<Page<T>>,
  deps: unknown[],
  pageSizeHint = 50
): CursorState<T> {
  const [items, setItems] = useState<T[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  const nextRef = useRef<string | null>(null);
  const itemsRef = useRef<T[]>([]);
  itemsRef.current = items;
  nextRef.current = next;

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    setItems([]);
    setError(null);
    loader()
      .then((page) => {
        if (!alive.current) return;
        setItems(page.items);
        setNext(page.next_cursor);
      })
      .catch((reason: unknown) => {
        if (alive.current) setError(reason instanceof Error ? reason.message : "加载失败");
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, pageSizeHint]);

  const loadMore = useCallback(() => {
    const cursor = nextRef.current;
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    loader(cursor)
      .then((page) => {
        if (!alive.current) return;
        setItems((current) => [...current, ...page.items]);
        setNext(page.next_cursor);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "加载更多失败"))
      .finally(() => setLoadingMore(false));
  }, [loader, loadingMore]);

  return { items, next, loading, loadingMore, error, reload: () => setTick((v) => v + 1), loadMore };
}

export function useInterval(callback: () => void, delay: number | null): void {
  const saved = useRef(callback);
  saved.current = callback;
  useEffect(() => {
    if (delay === null) return;
    const id = window.setInterval(() => saved.current(), delay);
    return () => window.clearInterval(id);
  }, [delay]);
}
