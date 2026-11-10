export interface Profil {
  name: string;
  aussprache: string;
  wesen: string;
  sprechweise: string;
  darf: string[];
  darf_nicht: string[];
  fremde: string;
  systemprompt: string;
}

export interface Version {
  id: number;
  erstellt: string;
  kommentar: string;
}

export interface ProfilAntwort {
  profil: Profil;
  version: Version | null;
  systemprompt: string;
  unveraendert?: boolean;
}

export interface Unterschied {
  feld: string;
  titel: string;
  zeilen: { art: "gleich" | "entfernt" | "neu"; text: string }[];
}

export interface VersionDetail extends Version {
  profil: Profil;
  unterschiede: Unterschied[];
}

export interface Nachricht {
  von: "nutzer" | "missa";
  text: string;
}

export const PROFIL = ["profil"] as const;
export const PROFIL_VERSIONEN = ["profil-versionen"] as const;

export function gleich(a: Profil, b: Profil): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
