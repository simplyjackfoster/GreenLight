#!/usr/bin/env ruby
# Fixes GreenLight.xcodeproj after architecture redesign:
# 1. Raises deployment target from iOS 14 to iOS 17
# 2. Removes legacy files from the app target's Compile Sources
# 3. Adds new architecture files to the app target's Compile Sources

$LOAD_PATH.unshift(File.expand_path("~/.gem/ruby/2.6.0/gems/xcodeproj-1.27.0/lib"))
require 'xcodeproj'

PROJECT_PATH = File.expand_path("GreenLight.xcodeproj", __dir__)
APP_ROOT     = File.expand_path("GreenLight", __dir__)

proj = Xcodeproj::Project.open(PROJECT_PATH)
app_target = proj.targets.find { |t| t.name == "GreenLight" }
raise "GreenLight target not found" unless app_target

# ── 1. Deployment target ─────────────────────────────────────────────────────
proj.build_configurations.each do |config|
  config.build_settings["IPHONEOS_DEPLOYMENT_TARGET"] = "17.0"
end
app_target.build_configurations.each do |config|
  config.build_settings["IPHONEOS_DEPLOYMENT_TARGET"] = "17.0"
end
puts "✓ Deployment target → iOS 17.0"

# ── 2. Legacy files to remove from target ────────────────────────────────────
REMOVE_PATHS = %w[
  ViewControllers/ViewController.swift
  ViewControllers/ViewControllerDetection.swift
  Telemetry/TelemetryLogger.swift
  App/SceneDelegate.swift
  Models/WebViewContainer.swift
  Detection/LightStateManager.swift
  Detection/Types.swift
  Detection/GeometryFilter.swift
]

sources_phase = app_target.source_build_phase
REMOVE_PATHS.each do |rel|
  full = File.join(APP_ROOT, rel)
  build_file = sources_phase.files.find { |f|
    f.file_ref&.real_path&.to_s == full rescue false
  }
  if build_file
    sources_phase.remove_build_file(build_file)
    puts "✓ Removed from target: #{rel}"
  else
    puts "  (skipped, not in target): #{rel}"
  end
end

# ── 3. New files to add ───────────────────────────────────────────────────────
ADD_PATHS = %w[
  App/AppEnvironment.swift
  Domain/DetectionResult.swift
  Domain/GeometryFilter.swift
  Domain/LightStateManager.swift
  Domain/Types.swift
  Features/Camera/CameraViewModel.swift
  Services/Protocols.swift
  Services/TelemetryService.swift
  Services/CameraService.swift
  Services/DetectionEngine.swift
  Services/LocationService.swift
]

# Helper: find or create the PBXGroup matching a relative folder path
def group_for(proj, app_root, folder_rel)
  # Walk from the main group, creating sub-groups as needed
  parts = folder_rel.split("/")
  # Find the GreenLight main group
  main_group = proj.main_group.children.find { |g|
    g.respond_to?(:path) && g.path == "GreenLight"
  }
  raise "GreenLight main group not found" unless main_group

  current = main_group
  parts.each do |part|
    child = current.children.find { |g| g.respond_to?(:path) && g.path == part }
    unless child
      child = current.new_group(part, part)
      puts "  Created group: #{part}"
    end
    current = child
  end
  current
end

ADD_PATHS.each do |rel|
  full = File.join(APP_ROOT, rel)
  unless File.exist?(full)
    puts "  (file missing on disk, skipping): #{rel}"
    next
  end

  # Skip if already in target
  already = sources_phase.files.any? { |f|
    f.file_ref&.real_path&.to_s == full rescue false
  }
  if already
    puts "  (already in target): #{rel}"
    next
  end

  folder_rel = File.dirname(rel)           # e.g. "App", "Domain", "Features/Camera"
  filename   = File.basename(rel)

  group = group_for(proj, APP_ROOT, folder_rel)

  # Add file reference if not already present
  file_ref = group.children.find { |f|
    f.respond_to?(:path) && f.path == filename
  }
  unless file_ref
    file_ref = group.new_file(full)
    file_ref.path = filename
    file_ref.source_tree = "<group>"
  end

  app_target.source_build_phase.add_file_reference(file_ref)
  puts "✓ Added to target: #{rel}"
end

# ── 4. Save ───────────────────────────────────────────────────────────────────
proj.save
puts "\n✓ project.pbxproj saved"
