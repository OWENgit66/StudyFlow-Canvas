"use client";
import { useEffect, useState } from "react";

export function useData<T>(load: () => Promise<T>, refreshKey: string | number = "") {
  const [retry, setRetry] = useState(0);
  const key = `${refreshKey}:${retry}`;
  const [state, setState] = useState<{ key: string; data?: T; error?: boolean }>();
  useEffect(() => {
    let active = true;
    load().then(
      data => { if (active) setState({ key, data }); },
      () => { if (active) setState({ key, error: true }); },
    );
    return () => { active = false; };
  }, [load, key]);
  return {
    data: state?.key === key ? state.data : undefined,
    error: state?.key === key && state.error,
    loading: state?.key !== key,
    retry: () => setRetry(value => value + 1),
  };
}
