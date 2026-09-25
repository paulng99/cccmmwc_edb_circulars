export type Programme = "all" | "circular" | "sister_school" | "lwlssg" | "other";
export type Topic =
  | "all"
  | "grant_funding"
  | "curriculum"
  | "admin"
  | "student_activity"
  | "parent_home"
  | "other";

export type Tone = "blue" | "green" | "amber" | "red" | "violet" | "teal" | "sky" | "orange" | "slate";

export const PROGRAMME_OPTIONS: { value: Programme; key: string }[] = [
  { value: "all", key: "programmeAll" },
  { value: "circular", key: "programmeCircular" },
  { value: "sister_school", key: "programmeSisterSchool" },
  { value: "lwlssg", key: "programmeLwlssg" },
  { value: "other", key: "programmeOther" },
];

export const TOPIC_OPTIONS: { value: Topic; key: string }[] = [
  { value: "all", key: "topicAll" },
  { value: "grant_funding", key: "topicGrantFunding" },
  { value: "curriculum", key: "topicCurriculum" },
  { value: "admin", key: "topicAdmin" },
  { value: "student_activity", key: "topicStudentActivity" },
  { value: "parent_home", key: "topicParentHome" },
  { value: "other", key: "topicOther" },
];

const PROGRAMME_KEY: Record<string, string> = {
  circular: "programmeCircular",
  sister_school: "programmeSisterSchool",
  lwlssg: "programmeLwlssg",
  other: "programmeOther",
};

const TOPIC_KEY: Record<string, string> = {
  grant_funding: "topicGrantFunding",
  curriculum: "topicCurriculum",
  admin: "topicAdmin",
  student_activity: "topicStudentActivity",
  parent_home: "topicParentHome",
  other: "topicOther",
};

/** One hue per programme so users learn the mapping quickly. */
export const PROGRAMME_TONE: Record<string, Tone> = {
  circular: "blue",
  sister_school: "violet",
  lwlssg: "teal",
  other: "slate",
};

export const TOPIC_TONE: Record<string, Tone> = {
  grant_funding: "green",
  curriculum: "sky",
  admin: "amber",
  student_activity: "orange",
  parent_home: "violet",
  other: "slate",
};

export function programmeLabel(prog: string | undefined, t: (key: string) => string): string {
  return t(PROGRAMME_KEY[prog || ""] || "programmeOther");
}

export function topicLabel(topic: string, t: (key: string) => string): string {
  return t(TOPIC_KEY[topic] || "topicOther");
}

export function langLabel(code: string, t: (key: string) => string): string {
  if (code === "zh-HK") return t("langZhHk");
  if (code === "zh-CN") return t("langZhCn");
  if (code === "en") return t("langEn");
  return code;
}

export function statusTone(status: string): Tone {
  switch (status) {
    case "ready":
    case "success":
    case "done":
      return "green";
    case "indexing":
    case "running":
    case "stored":
      return "amber";
    case "failed":
    case "error":
      return "red";
    case "cancelled":
      return "slate";
    default:
      return "slate";
  }
}
