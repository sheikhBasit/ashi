use std::process::Command;

/// Run a Python ASHI function tool and return JSON result.
/// args: ["functions.run_skill", "research", r#"{"topic":"ASHI"}"#]
#[tauri::command]
async fn run_ashi(module: String, args: Vec<String>) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/Projects/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);

    // Build: python -c "import sys; sys.path.insert(0,'functions'); from <module> import *; ..."
    // Simpler: call ashi CLI script directly
    let script = format!(
        "import sys, json; sys.path.insert(0, '{}/functions'); \
         parts = '{}'.split('.'); \
         mod = __import__(parts[-1]); \
         args = {}; \
         result = getattr(mod, parts[-1])(**args) if hasattr(mod, parts[-1]) else {{'error': 'not found'}}; \
         print(json.dumps(result))",
        ashi_dir,
        module,
        args.join(", ")
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Run a skill by name with context JSON.
#[tauri::command]
async fn run_skill(skill_name: String, context_json: String) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/Projects/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);

    let script = format!(
        r#"
import sys, json
sys.path.insert(0, '{ashi_dir}/functions')
from run_skill import run_skill
context = json.loads(r'''{context}''')
result = run_skill('{skill}', context)
print(json.dumps(result))
"#,
        ashi_dir = ashi_dir,
        skill = skill_name,
        context = context_json,
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Dispatch a tool call by name with JSON args.
#[tauri::command]
async fn dispatch_tool(tool_name: String, args_json: String) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/Projects/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);

    let script = format!(
        r#"
import sys, json
sys.path.insert(0, '{ashi_dir}/functions')
from tool_dispatch import dispatch
call = {{"tool": "{tool}", "args": json.loads(r'''{args}''')}}
result = dispatch(call)
print(json.dumps(result))
"#,
        ashi_dir = ashi_dir,
        tool = tool_name,
        args = args_json,
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Search the wiki with BM25.
#[tauri::command]
async fn search_wiki(query: String, top_k: usize) -> Result<String, String> {
    dispatch_tool(
        "search_wiki".to_string(),
        format!(
            r#"{{"query": "{}", "wiki_path": "~/Desktop/SecondBrain/wiki", "top_k": {}}}"#,
            query.replace('"', "\\\""),
            top_k
        ),
    )
    .await
}

/// List all available skills from the unified registry (ollama + claude plugins).
/// Returns JSON string: [{"name": str, "system": "ollama"|"claude", "description": str, ...}]
#[tauri::command]
fn list_skills() -> Result<String, String> {
    let registry_path = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi/skills/registry.json", h))
        .unwrap_or_else(|| {
            "/home/basitdev/Desktop/SecondBrain/Projects/ashi/skills/registry.json".to_string()
        });

    let content = std::fs::read_to_string(&registry_path)
        .map_err(|e| format!("Registry not found ({registry_path}): {e}. Run: ashi skill sync"))?;

    let registry: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("Registry parse error: {e}"))?;

    let skills_map = registry["skills"]
        .as_object()
        .ok_or("Registry missing 'skills' key")?;

    let mut skills: Vec<serde_json::Value> = skills_map
        .iter()
        .map(|(name, entry)| {
            let mut obj = entry.clone();
            obj["name"] = serde_json::Value::String(name.clone());
            obj
        })
        .collect();

    skills.sort_by(|a, b| {
        let sa = a["name"].as_str().unwrap_or("");
        let sb = b["name"].as_str().unwrap_or("");
        sa.cmp(sb)
    });

    serde_json::to_string(&skills).map_err(|e| e.to_string())
}

/// List active TCUs.
#[tauri::command]
fn list_tcus() -> Result<String, String> {
    let tasks_path = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/tasks/active", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/tasks/active".to_string());

    if !std::path::Path::new(&tasks_path).exists() {
        return Ok("[]".to_string());
    }

    let entries = std::fs::read_dir(&tasks_path)
        .map_err(|e| format!("Cannot read tasks dir: {}", e))?;

    let mut tcus: Vec<serde_json::Value> = entries
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.path()
                .extension()
                .map(|ext| ext == "json")
                .unwrap_or(false)
        })
        .filter_map(|e| {
            std::fs::read_to_string(e.path())
                .ok()
                .and_then(|s| serde_json::from_str(&s).ok())
        })
        .collect();

    tcus.sort_by(|a, b| {
        let ta = a["created_at"].as_str().unwrap_or("");
        let tb = b["created_at"].as_str().unwrap_or("");
        tb.cmp(ta)
    });

    serde_json::to_string(&tcus).map_err(|e| e.to_string())
}

/// Execute a shell command on the local machine and return JSON result.
#[tauri::command]
async fn run_shell(command: String, cwd: Option<String>, timeout: Option<u32>) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/Projects/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);

    let cwd_str = cwd.unwrap_or_else(|| {
        dirs_home()
            .map(|h| format!("{}/Desktop/SecondBrain", h))
            .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain".to_string())
    });
    let timeout_val = timeout.unwrap_or(30).min(120);

    let script = format!(
        r#"
import sys, json
sys.path.insert(0, '{ashi_dir}/functions')
from run_shell import run_shell
result = run_shell(
    command={command_repr},
    cwd={cwd_repr},
    timeout={timeout},
)
print(json.dumps(result))
"#,
        ashi_dir = ashi_dir,
        command_repr = serde_json::to_string(&command).unwrap_or_default(),
        cwd_repr = serde_json::to_string(&cwd_str).unwrap_or_default(),
        timeout = timeout_val,
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Collect full system monitor stats via monitor.get_all() and return JSON string.
#[tauri::command]
async fn get_monitor_stats() -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/Desktop/SecondBrain/Projects/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/Desktop/SecondBrain/Projects/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);

    let script = format!(
        r#"
import sys, json
sys.path.insert(0, '{ashi_dir}/functions')
from monitor import get_all
result = get_all()
print(json.dumps(result))
"#,
        ashi_dir = ashi_dir,
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Run the autonomous agent loop for a goal.
/// Returns JSON AgentResult.
#[tauri::command]
async fn run_agent(
    goal: String,
    max_steps: Option<u32>,
    require_confirmation: Option<bool>,
) -> Result<String, String> {
    let ashi_dir = dirs_home()
        .map(|h| format!("{}/workspace/ashi", h))
        .unwrap_or_else(|| "/home/basitdev/workspace/ashi".to_string());

    let venv_python = format!("{}/.venv/bin/python", ashi_dir);
    let steps = max_steps.unwrap_or(10);
    let confirm = require_confirmation.unwrap_or(true);

    let script = format!(
        r#"
import sys, json, dataclasses
sys.path.insert(0, '{ashi_dir}/functions')
from agent_runner import run_agent
result = run_agent(
    goal={goal_repr},
    max_steps={steps},
    require_confirmation={confirm_py},
    tasks_path='{ashi_dir}/../SecondBrain/tasks',
)
print(json.dumps(dataclasses.asdict(result)))
"#,
        ashi_dir = ashi_dir,
        goal_repr = serde_json::to_string(&goal).unwrap_or_default(),
        steps = steps,
        confirm_py = if confirm { "True" } else { "False" },
    );

    let output = Command::new(&venv_python)
        .args(["-c", &script])
        .current_dir(&ashi_dir)
        .output()
        .map_err(|e| format!("Failed to launch python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// Read full content of a wiki file by its path.
#[tauri::command]
fn read_wiki_file(path: String) -> Result<String, String> {
    // resolve ~ in path
    let resolved = if path.starts_with("~/") {
        dirs_home()
            .map(|h| format!("{}{}", h, &path[1..]))
            .unwrap_or(path.clone())
    } else {
        path.clone()
    };
    std::fs::read_to_string(&resolved)
        .map_err(|e| format!("Cannot read {}: {}", resolved, e))
}

fn dirs_home() -> Option<String> {
    std::env::var("HOME").ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            run_ashi,
            run_skill,
            dispatch_tool,
            search_wiki,
            read_wiki_file,
            list_skills,
            list_tcus,
            run_shell,
            get_monitor_stats,
            run_agent,
        ])
        .run(tauri::generate_context!())
        .expect("error while running ASHI app");
}
