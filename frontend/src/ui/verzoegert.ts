import { useEffect, useState } from "react";

/** Gibt den Wert erst weiter, wenn er sich kurz nicht geändert hat (damit nicht jeder Tastendruck sucht). */
export function useVerzoegert<T>(wert: T, millisekunden = 250): T {
  const [verzoegert, setVerzoegert] = useState(wert);
  useEffect(() => {
    const warten = window.setTimeout(() => setVerzoegert(wert), millisekunden);
    return () => window.clearTimeout(warten);
  }, [wert, millisekunden]);
  return verzoegert;
}
