export type PlantType = "DUKHAN" | "OTHER";

export interface PlantTypeOption {
  value: PlantType;
  label: string;
}

export interface Plant {
  id: number;
  plant_type: PlantType;
  code: string;
  name: string;
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  full_name: string | null;
}

export interface JobWarning {
  code: string;
  message: string;
  lines: number[];
}

export interface Job {
  id: number;
  created_at: string;
  plant_type: PlantType;
  plant_code: string | null;
  user_name: string | null;
  status: "SUCCESS" | "FAILED";
  error: string | null;
  input_filename: string;
  output_filename: string | null;
  submission_filename: string | null;
  spir_numbers: string[] | null;
  equipment_count: number;
  spare_count: number;
  line_count: number;
  warnings: JobWarning[] | null;
}

export type CombineKind = "WORKING" | "SUBMISSION";

export interface CombineTask {
  id: number;
  kind: CombineKind;
  status: "RUNNING" | "DONE" | "FAILED";
  done: number;
  total: number;
  error: string | null;
  filename: string | null;
}

export type PartField =
  | "part_number" | "tag_number" | "sap_material_number" | "material_temp_number" | "material_category"
  | "description" | "planning_plant" | "manufacturer_name" | "country_name" | "spir";

export interface Part {
  source: "CONVERSION" | "MASTER" | "BOTH"; // BOTH = conversion + material master merged into one row
  job_id: number | null;
  created_at: string | null;
  material_temp_number: string | null;
  material_category: string | null;
  part_number: string | null;
  description: string | null;
  tag_number: string | null;
  sap_material_number: string | null;
  planning_plant: string | null;
  manufacturer_name: string | null;
  country_name: string | null;
  spir: string | null;
}

export interface PartPage {
  items: Part[];
  total: number;
}

export interface JobPage {
  items: Job[];
  total: number;
}

export interface Profile {
  username: string;
  email: string | null;
  full_name: string | null;
  extraction_count: number;
  last_login: string;
}
