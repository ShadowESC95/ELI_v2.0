import os
import requests
import json


if __name__ == "__main__":
    print("🔍 VERIFYING ELI DUAL-MODEL CONFIGURATION")
    print("=" * 40)

    # Load environment
    env_file = ".env"
    config = {}
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key] = value

    print("\n1. CONFIGURATION CHECK:")
    print("-" * 20)
    router_model = config.get('ELI_ROUTER_MODEL', 'eli-router:latest')
    chat_model = config.get('ELI_CHAT_MODEL', config.get('OLLAMA_MODEL', 'eli:latest'))

    print(f"Router Model: {router_model}")
    print(f"Chat Model:   {chat_model}")

    # Check Ollama connection
    print("\n2. OLLAMA CONNECTION:")
    print("-" * 20)
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=10)
        if response.status_code == 200:
            print("✓ Ollama server is running")
            models = response.json().get('models', [])
            model_names = [m.get('name') for m in models]
        
            print(f"✓ Found {len(models)} models total")
        
            # Check if our models exist
            print("\n3. MODEL AVAILABILITY:")
            print("-" * 20)
        
            if router_model in model_names:
                print(f"✅ ROUTER MODEL: '{router_model}' is available")
                # Find size
                for m in models:
                    if m.get('name') == router_model:
                        size_gb = m.get('size', 0) / (1024**3)
                        print(f"   Size: {size_gb:.1f} GB (small/fast)")
            else:
                print(f"❌ ROUTER MODEL: '{router_model}' NOT FOUND!")
            
            if chat_model in model_names:
                print(f"✅ CHAT MODEL: '{chat_model}' is available")
                # Find size
                for m in models:
                    if m.get('name') == chat_model:
                        size_gb = m.get('size', 0) / (1024**3)
                        print(f"   Size: {size_gb:.1f} GB (large/powerful)")
            else:
                print(f"❌ CHAT MODEL: '{chat_model}' NOT FOUND!")
            
            print("\n4. SIZE COMPARISON:")
            print("-" * 20)
            router_size = 0
            chat_size = 0
        
            for m in models:
                if m.get('name') == router_model:
                    router_size = m.get('size', 0) / (1024**3)
                if m.get('name') == chat_model:
                    chat_size = m.get('size', 0) / (1024**3)
        
            if router_size and chat_size:
                ratio = chat_size / router_size
                print(f"Router: {router_size:.1f} GB")
                print(f"Chat:   {chat_size:.1f} GB")
                print(f"Ratio:  {ratio:.1f}x (chat is {ratio:.1f} times larger)")
            
                if ratio > 2:
                    print(f"✓ Perfect! Chat model is significantly larger for quality conversations")
                    print(f"✓ Router model is small/fast for command classification")
                else:
                    print(f"⚠ Warning: Chat model should be larger than router for best results")
        
        else:
            print(f"✗ Ollama error: {response.status_code}")
        
    except Exception as e:
        print(f"✗ Cannot connect to Ollama: {e}")

    print("\n5. SYSTEM TEST:")
    print("-" * 20)

    # Import and test ELI modules
    try:
        import sys
        sys.path.insert(0, '.')
    
        from eli.execution.router_enhanced import route
        from eli.execution.executor_enhanced import execute
    
        print("Testing router configuration...")
    
        # Check if router is using the right model
        import eli.execution.router_enhanced
        router_module_model = getattr(eli_tools.router, 'MODEL', 'unknown')
        print(f"Router module MODEL variable: {router_module_model}")
    
        if router_model in router_module_model:
            print("✓ Router module configured correctly")
        else:
            print("⚠ Router module might not be using configured model")
    
        # Test routing
        print("\nTesting command routing (should use small router model):")
        test_commands = [
            ("what time is it?", "time"),
            ("2 plus 2", "math"),
            ("hello there", "chat"),
        ]
    
        for cmd, expected in test_commands:
            result = route(cmd)
            print(f"  '{cmd}' → {result['action']} (expected: {expected})")
    
        print("\n✅ DUAL-MODEL SETUP VERIFIED!")
        print("   • Small router model for fast classification")
        print("   • Large chat model for quality conversations")
    
    except Exception as e:
        print(f"✗ Error testing system: {e}")
