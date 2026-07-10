require 'yaml'
require 'json'
require 'open-uri'
require 'uri'
require 'tempfile'

module Apidiff
  module SpecParser
    # ============ OPENAPI PARSING ============

    class OpenApiSpec
      attr_reader :info, :paths, :schemas, :components, :servers
      
      def initialize(spec_hash)
        @info = spec_hash['info'] || {}
        @paths = spec_hash['paths'] || {}
        @schemas = spec_hash['components']['schemas'] || {}
        @components = spec_hash['components'] || {}
        @servers = spec_hash['servers'] || []
      end

      def operation_key(path, method)
        "#{method.upcase} #{path}"
      end

      def operations
        result = {}
        paths.each do |path, path_item|
          (path_item.methods || {}).each do |method|
            next unless %w[get post put delete patch].include?(method.to_s)
            op = path_item[method]
            key = operation_key(path, method)
            result[key] = {
              path: path,
              method: method,
              summary: op['summary'],
              description: op['description'],
              params: extract_params(op),
              responses: op['responses'] || {},
              operation_id: op['operationId'],
              security: op['security']
            }
          end
        end
        result.sort.to_h
      end

      def extract_params(operation)
        params = []
        
        # Query parameters
        (params = operation['parameters'])&.each do |p|
          param = {
            name: p['name'],
            in: p['in'] || 'query',
            required: p['required'],
            schema: extract_schema(p)
          }
          params << param
        end
        
        # Header parameters (move to query for comparison purposes)
        (headers = operation['x-header-params'])&.each do |h|
          param = {
            name: h['name'] || 'header',
            in: 'header',
            required: false,
            schema: extract_schema(h)
          }
          params << param
        end
        
        params.sort_by(&:name).to_h
      end

      def extract_schema(schema_def)
        {
          type: schema_def['type'] || (schema_def['properties'] ? :object : :any),
          properties: schema_def['properties'],
          required: schema_def['required'] || [],
          format: schema_def['format'],
          example: schema_def['example']
        }
      end

      def all_schemas
        schemas.transform_values do |s|
          extract_schema(s) if s.is_a?(Hash)
        end.to_h
      end

      def deprecated_operations
        paths.flat_map do |path, path_item|
          (path_item.methods || {}).map do |method|
            op = path_item[method]
            next unless %w[get post put delete patch].include?(method.to_s)
            if op['x-deprecated'] == true || 
               (op['description']&.include?('@deprecated'))
              { path: path, method: method }
            end
          end.compact
        end.flatten
      end
    end

    # ============ GRAPHQL PARSING ============

    class GraphQLSpec
      attr_reader :types, :query_type, :mutation_type
      
      def initialize(sdl_string)
        @raw_sdl = sdl_string
        parse_sdl
      end

      def parse_sdl
        lines = @raw_sdl.lines.map(&:strip).reject { |l| l.empty? || l.start_with?('#') }
        
        # Simple state machine parser for SDL
        current_type = nil
        in_fields = false
        
        types = {}
        
        lines.each do |line|
          if line.match?(/^(scalar|enum|input|interface|union|type)\s+(\w+)/)
            type_name, kind = $2, $3
            current_type = { name: type_name, kind: kind }
            
            case kind
            when 'scalar', 'enum'
              types[type_name] = { kind: kind, values: [] }
            when 'input'
              types[type_name] = { kind: :input, fields: {} }
            when 'interface'
              types[type_name] = { kind: :interface, implements: [], fields: {} }
            when 'union'
              types[type_name] = { kind: :union, members: [] }
            when 'type'
              if current_type[:kind] == :input
                current_type[:fields] = {}
              end
              in_fields = true
            end
            
            next
          end

          if in_fields && line.match?(/^(field|directive)\s+(\w+)/)
            field_name, directive = $2, $3
            if directive == 'field'
              # Parse field definition: name(args): type @deprecated
              parts = line.split(':')
              field_part = parts[0].strip
              
              if field_part.include?('(')
                args_str, type_str = field_part.split(/(\([^)]+\)):/)
                args = parse_args(args_str)
                type_str = type_str.strip
                
                # Parse type with optional directives
                type_info = parse_type(type_str)
                
                current_type[:fields][field_name] = {
                  args: args,
                  type: type_info,
                  deprecated: line.include?('@deprecated')
                }
              end
            elsif directive == 'directive'
              # Parse @deprecated or similar directives
              if field_part.include?('deprecated')
                current_type[:fields].each do |fn, fdef|
                  fdef[:deprecated] = true
                end
              end
            end
          end

          in_fields = false unless line.match?(/^(type|input)\s+(\w+)/)
        end
        
        # Set default types if not found
        @query_type = 'Query'
        @mutation_type = 'Mutation'
        
        # Find Query and Mutation types
        ['Query', 'Mutation'].each do |tname|
          next unless types[tname]
          
          case types[tname][:kind]
          when :input, :type
            if tname == 'Query'
              @query_type = tname
            elsif tname == 'Mutation'
              @mutation_type = tname
            end
          end
        end
        
        # Convert to hash format for easier access
        types.transform_values do |t|
          case t[:kind]
          when :input, :type, :interface
            { kind: t[:kind], fields: t[:fields] || {} }
          when :union
            { kind: :union, members: t[:members] || [] }
          else
            { kind: t[:kind], values: t[:values] || [] }
          end
        end
        
        @types = types.to_h
      end

      def parse_args(args_str)
        args = {}
        if args_str.include?(',')
          args_str.split(',').each do |arg|
            parts = arg.strip.split('=')
            name = parts[0].strip
            default = parts[1] ? { default: parts[1].strip } : {}
            args[name] = default
          end
        else
          args['required'] = true
        end
        args
      end

      def parse_type(type_str)
        # Parse "String!", "String", "[Int!]", etc.
        type_info = { required: false, list: false }
        
        if type_str.include?('!')
          type_info[:required] = true
          type_str = type_str.gsub('!', '')
        end
        
        if type_str.start_with?('[') && type_str.end_with?(']')
          type_info[:list] = true
          inner_type = type_str[1..-2].strip
          type_info[:type] = parse_type(inner_type)
        else
          # Map GraphQL types to Ruby/JSON equivalents
          case type_str.downcase
          when 'string' then type_info[:type] = :string
          when 'int', 'integer' then type_info[:type] = :integer
          when 'float', 'double' then type_info[:type] = :float
          when 'boolean', 'bool' then type_info[:type] = :boolean
          when 'id' then type_info[:type] = :string
          else type_info[:type] = :any
        end
        
        type_info
      end

      def all_fields
        result = {}
        
        # Query fields
        if @query_type && types[@query_type]
          query_fields = types[@query_type][:fields] || {}
          result['Query'] = query_fields.transform_values do |f|
            { name: f.keys.first, **f.values.first } if f.size > 0
          end
        end
        
        # Mutation fields  
        if @mutation_type && types[@mutation_type]
          mutation_fields = types[@mutation_type][:fields] || {}
          result['Mutation'] = mutation_fields.transform_values do |f|
            { name: f.keys.first, **f.values.first } if f.size > 0
          end
        end
        
        # Object type fields (excluding Query/Mutation)
        types.each_value do |t|
          next unless t[:kind] == :type && !['Query', 'Mutation'].include?(t[:name])
          obj_fields = t[:fields] || {}
          result[t[:name]] = obj_fields.transform_values do |f|
            { name: f.keys.first, **f.values.first } if f.size > 0
          end
        end
        
        result.to_h
      end

      def deprecated_fields
        fields = all_fields
        result = []
        
        fields.each_value do |type_name, type_data|
          (type_data || {}).each_value do |field_def|
            next unless field_def[:deprecated] == true
            result << { type: type_name, field: field_def[:name] }
          end
        end
        
        result
      end

      def all_types
        types.transform_values do |t|
          case t[:kind]
          when :input, :type, :interface
            { name: t[:name], kind: t[:kind], fields_count: (t[:fields]&.size || 0) }
          when :union
            { name: t[:name], kind: :union, members: t[:members] || [] }
          else
            { name: t[:name], kind: t[:kind], values: t[:values] || [] }
          end
        end.to_h
      end
    end

    # ============ BREAKING CHANGE DETECTOR ============

    class BreakingChangeDetector
      attr_reader :openapi_changes, :graphql_changes
      
      def initialize(openapi_old: nil, openapi_new: nil, 
                     graphql_old: nil, graphql_new: nil)
        @openapi_old = openapi_old
        @openapi_new = openapi_new
        @graphql_old = graphql_old
        @graphql_new = graphql_new
        
        detect_openapi_changes if @openapi_old && @openapi_new
        detect_graphql_changes if @graphql_old && @graphql_new
      end

      def has_breaking_changes?
        !breaking_changes.empty?
      end

      def breaking_changes
        result = []
        
        result << openapi_changes unless openapi_changes.nil? || openapi_changes.empty?
        result << graphql_changes unless graphql_changes.nil? || graphql_changes.empty?
        
        result.flatten.sort_by { |c| c[:severity] || 0 }
      end

      def severity_of_change(change)
        case change[:type]
        when :removed, :required_added
          3
        when :deprecated_removed
          2
        when :type_changed
          1
        else
          0
        end
      end

      private

      def detect_openapi_changes
        old_ops = @openapi_old&.operations || {}
        new_ops = @openapi_new&.operations || {}
        
        # Find removed operations (breaking)
        removed = []
        old_ops.each do |key, op|
          unless new_ops[key]
            removed << { type: :removed, key: key, operation: op }
          end
        end
        
        # Find added operations (usually safe but worth noting)
        added = []
        new_ops.each do |key, op|
          unless old_ops[key]
            added << { type: :added, key: key, operation: op }
          end
        end
        
        openapi_changes = { removed: removed, added: added }
      end

      def detect_graphql_changes
        old_fields = @graphql_old&.all_fields || {}
        new_fields = @graphql_new&.all_fields || {}
        
        # Find removed fields (breaking)
        removed = []
        old_fields.each do |type_name, type_data|
          next unless type_data.is_a?(Hash) && !['Query', 'Mutation'].include?(type_name)
          
          (type_data.keys - new_fields[type_name].keys).each do |field_name|
            removed << { type: :removed, parent: type_name, field: field_name }
          end if type_data.keys.any? & !new_fields[type_name]
        end
        
        # Find deprecated fields that are still used (warning)
        old_deprecated = @graphql_old&.deprecated_fields || []
        new_deprecated = @graphql_new&.deprecated_fields || []
        
        deprecated_removed = []
        old_deprecated.each do |d|
          unless new_deprecated.find { |nd| nd[:type] == d[:type] && nd[:field] == d[:field] }
            deprecated_removed << d
          end
        end
        
        graphql_changes = { removed: removed, deprecated_removed: deprecated_removed }
      end
    end

    # ============ FILE HANDLER ============

    class SpecFileHandler
      def self.load_openapi(path)
        content = File.read(path)
        if content.include?(':') && !content.match?(/<\?xml/)
          spec_hash = YAML.safe_load(content, permitted_classes: [Date, Time]) || 
                      JSON.parse(content)
        else
          # Assume XML or other format - try to parse as is
          spec_hash = { 'info' => {}, 'paths' => {} }
        end
        
        OpenApiSpec.new(spec_hash)
      rescue Psych::SyntaxError, JSON::ParserError, StandardError => e
        raise "Failed to parse OpenAPI spec: #{e.message}"
      end

      def self.load_graphql(path)
        content = File.read(path)
        GraphQLSpec.new(content)
      rescue StandardError => e
        raise "Failed to parse GraphQL SDL: #{e.message}"
      end
    end

    # ============ MAIN INTERFACE ============

    class ApidiffRunner
      def self.run(openapi_old_path: nil, openapi_new_path: nil,
                   graphql_old_path: nil, graphql_new_path: nil)
        changes = BreakingChangeDetector.new(
          openapi_old: SpecFileHandler.load_openapi(openapi_old_path),
          openapi_new: SpecFileHandler.load_openapi(openapi_new_path),
          graphql_old: SpecFileHandler.load_graphql(graphql_old_path),
          graphql_new: SpecFileHandler.load_graphql(graphql_new_path)
        )

        puts "\n=== APIDIFF RESULTS ==="
        puts "Has breaking changes: #{changes.has_breaking_changes?}"
        
        changes.breaking_changes.each do |change|
          severity = severity_of_change(change)
          marker = case severity
                  when 3 then "BREAKING"
                  when 2 then "WARNING"
                  else "INFO"
                end
        
        puts "\n#{marker}: #{change.inspect}"
      end

      def self.demo
        # Sample OpenAPI specs for demo
        old_openapi = <<~YAML
openapi: 3.0.1
info:
  title: Old API
  version: 1.0.0
paths:
  /users:
    get:
      summary: Get users
      operationId: getUsers
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  items:
                    type: array
                    items:
                      $ref: '#/components/schemas/User'
  /posts/{id}:
    get:
      summary: Get post
      operationId: getPost
      parameters:
        - name: id
          in: path
          required: true