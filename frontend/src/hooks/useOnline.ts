/**
 * Whether this device currently has a network connection.
 *
 * `navigator.onLine` is a lie on some platforms (it reports true on a captive portal, and
 * older Safari reported true with no connection at all), so it is treated as a hint that
 * only ever makes the UI more cautious: when it says offline, the app says offline and stops
 * pretending a send could work. It is never used to claim "you are connected" - only an
 * actual API answer proves that.
 */

import { useEffect, useState } from "react";

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine !== false);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
